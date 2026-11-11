"""Actions the assistant proposes and a person approves: create a task, add a note, send an email.

The assistant only drafts (agent/tools.py); the chat route saves each draft here as a proposal row. The
row is the only authority on whether an action runs. A decision locks it and requires 'pending', then
checks permission, re-reads the live source records, executes, reads the result back and writes the
audit rows, all in the request's transaction: either all of it lands or none of it does.

A refusal or a failed recheck is an answer, not an error, so its audit row is committed with it.
"""

from datetime import datetime
from typing import Literal

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from apps.api import routes
from apps.api.agent import graph, tools
from apps.api.auth import Csm, Viewer
from apps.api.db import Db, audit

router = APIRouter(tags=["actions"])


VERBS = {"send_email": "send email", "create_task": "create tasks", "add_note": "add notes"}


class Proposal(BaseModel):
    proposal_id: int
    conversation_id: str
    action: str
    account_id: str
    params: dict
    status: Literal["pending", "done", "rejected", "refused", "blocked"]
    outcome: dict  # reason (refused, rejected), changes (blocked) or what was created (done)
    created_at: datetime
    decided_at: datetime | None


class Decision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    params: dict = {}  # edit: the fields to change before approving


def refusal(db: psycopg.Connection, user: dict, action: str, account_id: str) -> str | None:
    """Why this user may not take this action on this account, or None when they may."""
    if user["role"] == "viewer":
        return f"Viewers cannot {VERBS[action]}; ask a CSM or an admin."
    if action == "send_email" and user["role"] != "admin":
        owner = db.execute(
            "select owner_email from marts.dim_account where account_id = %s", (account_id,)
        ).fetchone()
        if not owner or owner["owner_email"].lower() != user["email"].lower():
            return "Only the account's owner or an admin can email its contacts."
    return None


def save(db: psycopg.Connection, user: dict, conversation_id: str, drafts: list[dict]) -> list:
    """Save an answer's drafts as proposals. Call it in the transaction that answers the message."""
    return [_propose(db, user, conversation_id, draft) for draft in drafts]


def _propose(db: psycopg.Connection, user: dict, conversation_id: str, draft: dict) -> dict:
    """Pending, or refused at once when the user may not take this action."""
    reason = refusal(db, user, draft["action"], draft["account_id"])
    row = db.execute(
        "insert into app.proposals "
        "(user_id, conversation_id, action, account_id, params, snapshot, status, outcome) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s) returning *",
        (
            user["user_id"],
            conversation_id,
            draft["action"],
            draft["account_id"],
            Jsonb(draft["params"]),
            Jsonb(draft["snapshot"]),
            "refused" if reason else "pending",
            Jsonb({"reason": reason} if reason else {}),
        ),
    ).fetchone()
    _audit(db, user, row, "refused" if reason else "proposed", {"params": row["params"]})
    return Proposal(**row).model_dump(mode="json")


def recheck(
    db: psycopg.Connection, sources: httpx.Client, user: dict, row: dict, params: dict
) -> list[str]:
    """What changed in the live records since the draft. Empty when it is safe to go ahead."""
    account_id, changes = row["account_id"], []
    try:
        account = sources.get(f"/crm/accounts/{account_id}")
        if account.status_code == 404:
            return [f"Account {account_id} no longer exists in the CRM."]
        account.raise_for_status()
        if row["action"] == "send_email":
            # The warehouse's owner can be an hour old; the CRM's is the one that counts.
            owner = account.json()["owner_email"]
            if user["role"] != "admin" and owner.lower() != user["email"].lower():
                changes.append(
                    f"The account's owner in the CRM is now {owner}; only the owner or an admin "
                    "can email its contacts."
                )
            contacts = sources.get(f"/crm/accounts/{account_id}/contacts")
            contacts.raise_for_status()
            active = {c["email"].lower() for c in contacts.json() if c["is_active"]}
            if params["to_email"].lower() not in active:
                changes.append(f"{params['to_email']} is not an active contact of this account.")
            if was := row["snapshot"].get("ticket"):
                live = sources.get(f"/helpdesk/tickets/{was['ticket_id']}")
                live.raise_for_status()
                if (now := live.json()["status"]) != was["status"]:
                    changes.append(
                        f"Ticket {was['ticket_id']} is now {now}; it was {was['status']} when "
                        "the email was drafted."
                    )
    except httpx.HTTPError as error:  # fail closed: no live check, no write
        return [f"Could not recheck the live records: {error}"]
    if row["action"] == "create_task":
        if (email := params.get("assignee_email")) and not db.execute(
            "select 1 from app.users where email = %s", (email.lower(),)
        ).fetchone():
            changes.append(f"There is no Nexo user {email} to assign the task to.")
        duplicate = db.execute(
            "select task_id from app.tasks "
            "where account_id = %s and lower(title) = lower(%s) and status = 'open'",
            (account_id, params["title"]),
        ).fetchone()
        if duplicate:
            changes.append(
                f"An open task with this title already exists (task {duplicate['task_id']})."
            )
    return changes


def execute(db: psycopg.Connection, user: dict, row: dict, params: dict) -> dict:
    """Take the action and read the result back. Returns what was created."""
    account_id = row["account_id"]
    if row["action"] == "add_note":
        created = {
            "note_id": routes.add_note(account_id, routes.NoteIn(**params), db, user).note_id
        }
        check = ("select 1 from app.notes where note_id = %s", created["note_id"])
    elif row["action"] == "create_task":
        task = routes.add_task(account_id, routes.TaskIn(**params), db, user)
        created = {"task_id": task["task_id"]}
        check = ("select 1 from app.tasks where task_id = %s", created["task_id"])
    else:
        email_id = db.execute(
            "insert into app.outbox (proposal_id, account_id, to_email, subject, body) "
            "values (%s, %s, %s, %s, %s) returning email_id",
            (row["proposal_id"], account_id, params["to_email"], params["subject"], params["body"]),
        ).fetchone()["email_id"]
        created = {"email_id": email_id}  # queued; apps/api/outbox.py delivers it within 30 seconds
        check = ("select 1 from app.outbox where email_id = %s and status = 'queued'", email_id)
    _audit(db, user, row, "executed", created)
    if not db.execute(check[0], (check[1],)).fetchone():  # rolls the whole decision back
        raise RuntimeError(f"Proposal {row['proposal_id']} ran but its result cannot be read back")
    _audit(db, user, row, "verified", created)
    return created


def decide(
    db: psycopg.Connection, sources: httpx.Client, user: dict, proposal_id: int, decision: Decision
) -> tuple[dict, bool]:
    """The proposal after the decision, and whether this call decided it (False: it already was)."""
    row = db.execute(
        "select * from app.proposals where proposal_id = %s and user_id = %s for update",
        (proposal_id, user["user_id"]),
    ).fetchone()
    if not row:  # someone else's proposal looks the same as a missing one
        raise HTTPException(404, f"No proposal {proposal_id}")
    if row["status"] != "pending":  # already decided, for example by a double click
        return Proposal(**row).model_dump(mode="json"), False
    if decision.decision == "reject":
        rejected = _close(db, user, row, row["params"], "rejected", {"reason": "Rejected by you."})
        return rejected, True

    edits = decision.params if decision.decision == "edit" else {}
    if row["action"] == "send_email" and "ticket_id" in edits:
        raise HTTPException(
            422, "The ticket an email is about cannot be changed; reject it instead"
        )
    try:
        params = tools.PARAMS[row["action"]](**(row["params"] | edits)).model_dump(mode="json")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    if reason := refusal(db, user, row["action"], row["account_id"]):
        return _close(db, user, row, params, "refused", {"reason": reason}), True
    if changes := recheck(db, sources, user, row, params):
        return _close(db, user, row, params, "blocked", {"changes": changes}), True
    _audit(db, user, row, "approved", {"params": params, "edited": sorted(edits)})
    return _close(db, user, row, params, "done", execute(db, user, row, params)), True


def _close(db, user: dict, row: dict, params: dict, status: str, outcome: dict) -> dict:
    row = db.execute(
        "update app.proposals set status = %s, outcome = %s, params = %s, decided_at = now() "
        "where proposal_id = %s returning *",
        (status, Jsonb(outcome), Jsonb(params), row["proposal_id"]),
    ).fetchone()
    if status != "done":  # a done action already has its executed and verified rows
        _audit(db, user, row, status, outcome)
    return Proposal(**row).model_dump(mode="json")


def _audit(db, user: dict, row: dict, event: str, detail: dict) -> None:
    detail = {"action": row["action"], **detail}
    audit(
        db,
        user,
        f"action.{event}",
        account_id=row["account_id"],
        target=("proposal", row["proposal_id"]),
        detail=detail,
    )


def describe(proposal: dict) -> str:
    """One sentence on how a decision ended, for the conversation's history."""
    what, status = proposal["action"].split("_")[-1], proposal["status"]
    if status == "done":
        return f"The {what} was approved and " + ("queued to send." if what == "email" else "done.")
    detail = proposal["outcome"].get("reason") or " ".join(proposal["outcome"].get("changes", []))
    return f"The {what} was not done ({status}): {detail}"


@router.get("/actions")
def list_proposals(db: Db, user: Viewer, status: str | None = None) -> list[Proposal]:
    """Your proposals, newest first; pass status=pending for the ones waiting on you."""
    return db.execute(
        "select * from app.proposals where user_id = %s and (%s::text is null or status = %s) "
        "order by proposal_id desc limit 100",
        (user["user_id"], status, status),
    ).fetchall()


@router.post("/actions/{proposal_id}/decision")
def decide_route(
    proposal_id: int, decision: Decision, request: Request, db: Db, user: Csm
) -> Proposal:
    """Approve, edit or reject a proposal. A refusal or a changed record comes back as its status."""
    proposal, decided_now = decide(db, request.app.state.sources, user, proposal_id, decision)
    if not decided_now:  # a repeated click: the history already has this outcome
        return proposal
    # The conversation remembers the outcome, so a follow-up question knows what happened.
    compiled = request.app.state.agent["graph"]
    config = {"configurable": {"thread_id": graph.thread_id(user, proposal["conversation_id"])}}
    history = compiled.get_state(config).values.get("history", [])
    entry = {"question": f"Decision on proposal {proposal_id}", "summary": describe(proposal)}
    compiled.update_state(config, {"history": [*history, entry][-10:]}, as_node="finish")
    return proposal
