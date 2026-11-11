"""Actions: nothing runs without approval, a permission check and a live recheck, and all is audited."""

import httpx
import psycopg
import pytest

from apps.api.main import app
from data.synthetic.generate import ACME, OWNERS

EMAIL = "Email Acme's admin about the import ticket."


@pytest.fixture(scope="module")
def owner(api):
    """A CSM who owns Acme, and so may email its contacts."""
    email = next(a["owner_email"] for a in api.data["accounts"] if a["account_id"] == ACME)
    return api.sign_in(email)


def ask(client, conversation: str, message: str) -> dict:
    reply = client.post(f"/conversations/{conversation}/messages", json={"message": message})
    assert reply.status_code == 200, reply.text
    return reply.json()


def decide(client, proposal_id: int, decision: str, **params) -> httpx.Response:
    body = {"decision": decision, "params": params}
    return client.post(f"/actions/{proposal_id}/decision", json=body)


def query(api, sql: str, *params) -> list[tuple]:
    with psycopg.connect(api.url) as conn:
        return conn.execute(sql, params).fetchall()


def audit_trail(api, proposal_id: int) -> list[str]:
    return [
        action
        for (action,) in query(
            api,
            "select action from audit.events where target_type = 'proposal' and target_id = %s "
            "order by event_id",
            str(proposal_id),
        )
    ]


def test_an_email_is_sent_only_after_approval_and_only_once(api, owner):
    [proposal] = ask(owner, "email-1", EMAIL)["proposals"]
    assert proposal["action"] == "send_email" and proposal["status"] == "pending"
    assert proposal["params"]["subject"].startswith("Re: Bulk CSV import")
    pid = proposal["proposal_id"]
    assert query(api, "select count(*) from app.outbox where proposal_id = %s", pid) == [(0,)]

    first, second = decide(owner, pid, "approve").json(), decide(owner, pid, "approve").json()
    assert first["status"] == "done" and second == first  # a double click changes nothing
    assert query(api, "select status from app.outbox where proposal_id = %s", pid) == [("queued",)]
    assert audit_trail(api, pid) == [
        "action.proposed",
        "action.approved",
        "action.executed",
        "action.verified",
    ]
    history = owner.get("/conversations/email-1").json()
    assert history[-1]["summary"] == "The email was approved and queued to send."
    assert history[-2]["summary"] != history[-1]["summary"]  # the double click added nothing


def test_a_ticket_that_changed_since_the_draft_stops_the_email(api, owner):
    [proposal] = ask(owner, "email-2", EMAIL)["proposals"]
    ticket = proposal["params"]["ticket_id"]
    assert api.sources.patch(f"/helpdesk/tickets/{ticket}", json={"status": "solved"}).is_success

    blocked = decide(owner, proposal["proposal_id"], "approve").json()
    assert blocked["status"] == "blocked"
    assert "is now solved; it was open" in blocked["outcome"]["changes"][0]
    pid = proposal["proposal_id"]
    assert query(api, "select count(*) from app.outbox where proposal_id = %s", pid) == [(0,)]
    assert audit_trail(api, pid) == ["action.proposed", "action.blocked"]
    api.sources.patch(f"/helpdesk/tickets/{ticket}", json={"status": "open"})


def test_an_owner_change_in_the_crm_stops_the_old_owners_email(api, owner):
    [proposal] = ask(owner, "email-7", EMAIL)["proposals"]
    account = api.sources.get(f"/crm/accounts/{ACME}").json()
    new_owner = {"owner_name": "Daniel Reyes", "owner_email": "daniel.reyes@nexo.example"}
    api.sources.patch(f"/crm/accounts/{ACME}", json=new_owner).raise_for_status()
    try:
        blocked = decide(owner, proposal["proposal_id"], "approve").json()
    finally:
        old = {"owner_name": account["owner_name"], "owner_email": account["owner_email"]}
        api.sources.patch(f"/crm/accounts/{ACME}", json=old)
    assert blocked["status"] == "blocked"
    reason = (
        "The account's owner in the CRM is now daniel.reyes@nexo.example; only the owner or an "
        "admin can email its contacts."
    )
    assert blocked["outcome"]["changes"] == [reason]


def test_an_edited_email_must_still_go_to_an_active_contact(api, owner):
    [proposal] = ask(owner, "email-3", EMAIL)["proposals"]
    pid = proposal["proposal_id"]
    assert decide(owner, pid, "edit", ticket_id="tkt_other").status_code == 422
    assert decide(owner, pid, "edit", subject="").status_code == 422
    edited = decide(owner, pid, "edit", to_email="someone@elsewhere.example").json()
    assert edited["status"] == "blocked"
    assert edited["outcome"]["changes"] == [
        "someone@elsewhere.example is not an active contact of this account."
    ]


def test_who_may_act(api, owner):
    # A viewer's request is refused when it is made, with the reason, and the refusal is audited.
    [refused] = ask(api.viewer, "email-4", EMAIL)["proposals"]
    assert refused["status"] == "refused"
    assert refused["outcome"]["reason"].startswith("Viewers cannot send email")
    assert audit_trail(api, refused["proposal_id"]) == ["action.refused"]
    assert decide(api.viewer, refused["proposal_id"], "approve").status_code == 403

    # A CSM may email only the contacts of accounts they own.
    acme_owner = next(a["owner_email"] for a in api.data["accounts"] if a["account_id"] == ACME)
    other = next(email for _, email in OWNERS if email != acme_owner)
    [not_owner] = ask(api.sign_in(other), "email-5", EMAIL)["proposals"]
    assert (
        not_owner["outcome"]["reason"]
        == "Only the account's owner or an admin can email its contacts."
    )

    # Someone else's proposal looks the same as a missing one.
    [pending] = ask(owner, "email-6", EMAIL)["proposals"]
    assert decide(api.admin, pending["proposal_id"], "approve").status_code == 404
    assert decide(owner, 999999, "approve").status_code == 404


def test_a_task_runs_once_approved_and_a_rejected_note_never_does(api, owner):
    [task] = ask(owner, "task-1", "Create a follow up task for Acme")["proposals"]
    done = decide(owner, task["proposal_id"], "approve").json()
    assert done["status"] == "done"
    assert query(
        api,
        "select t.title, u.email from app.tasks t join app.users u on u.user_id = t.assignee_id "
        "where t.task_id = %s",
        done["outcome"]["task_id"],
    ) == [("Follow up with Acme Corp", task["params"]["assignee_email"])]
    # The same task again would be a duplicate of the open one.
    [again] = ask(owner, "task-2", "Create a follow up task for Acme")["proposals"]
    assert decide(owner, again["proposal_id"], "approve").json()["status"] == "blocked"

    [note] = ask(owner, "note-1", "Add a note to Acme: asked for a call next week")["proposals"]
    assert note["params"]["body"] == "asked for a call next week"
    rejected = decide(owner, note["proposal_id"], "reject").json()
    assert rejected["status"] == "rejected"
    assert query(api, "select count(*) from app.notes where body = %s", note["params"]["body"]) == [
        (0,)
    ]
    assert owner.get("/actions?status=pending").status_code == 200


def test_no_live_recheck_means_no_write(api, owner):
    [note] = ask(owner, "note-2", "Add a note to Acme: renewal call booked")["proposals"]
    reachable, app.state.sources = (
        app.state.sources,
        httpx.Client(base_url="http://127.0.0.1:9", timeout=0.5),
    )
    try:
        blocked = decide(owner, note["proposal_id"], "approve").json()
    finally:
        app.state.sources = reachable
    assert blocked["status"] == "blocked"
    assert blocked["outcome"]["changes"][0].startswith("Could not recheck the live records")


def test_no_action_ever_ran_without_an_approval(api, owner):
    # The phase gate: every executed action has an approval row before it.
    unapproved = query(
        api,
        "select count(*) from audit.events e where e.action = 'action.executed' and not exists "
        "(select 1 from audit.events a where a.action = 'action.approved' "
        "and a.target_id = e.target_id and a.event_id < e.event_id)",
    )
    assert unapproved == [(0,)]
    assert (
        query(api, "select count(*) from audit.events where action = 'action.executed'")[0][0] > 0
    )


def test_approved_emails_are_sent_retried_or_only_logged(api, owner, monkeypatch):
    from psycopg.rows import dict_row

    from apps.api import outbox

    def approve(conversation: str) -> int:
        [proposal] = ask(owner, conversation, EMAIL)["proposals"]
        return decide(owner, proposal["proposal_id"], "approve").json()["outcome"]["email_id"]

    def state(email_id: int) -> tuple:
        sql = "select status, attempts from app.outbox where email_id = %s"
        return query(api, sql, email_id)[0]

    with psycopg.connect(api.url, autocommit=True, row_factory=dict_row) as conn:
        # No mail server set: nothing is delivered, and the email says so.
        monkeypatch.delenv("NEXO_SMTP_HOST", raising=False)
        logged = approve("send-1")
        outbox.send_queued(conn)
        assert state(logged) == ("logged", 1)

        sent_messages = []
        sent = approve("send-2")
        assert outbox.send_queued(conn, deliver=sent_messages.append) == {"sent": 1}
        assert state(sent) == ("sent", 1)
        [message] = sent_messages
        assert message["Reply-To"] == owner.get("/auth/me").json()["email"]
        assert message["Subject"].startswith("Re: Bulk CSV import")

        def server_down(message):
            raise ConnectionRefusedError("no server")

        retried = approve("send-3")
        assert outbox.send_queued(conn, deliver=server_down) == {"retry": 1}
        assert state(retried) == ("queued", 1)
        conn.execute("update app.outbox set attempts = %s where email_id = %s", (4, retried))
        assert outbox.send_queued(conn, deliver=server_down) == {"failed": 1}
        assert state(retried) == ("failed", 5)

    events = query(
        api,
        "select action from audit.events where target_type = 'email' and target_id = %s "
        "order by event_id",
        str(retried),
    )
    assert events == [("email.retry",), ("email.failed",)]


def test_the_web_can_trace_an_approval_and_its_task(api, owner):
    [proposal] = ask(owner, "trace-1", "Create a follow up task for Fenwyck")["proposals"]
    done = decide(owner, proposal["proposal_id"], "approve").json()
    trail = owner.get(
        "/audit", params={"target_type": "proposal", "target_id": proposal["proposal_id"]}
    ).json()
    assert [e["action"] for e in trail] == [
        "action.verified",
        "action.executed",
        "action.approved",
        "action.proposed",
    ]
    assert {e["action"] for e in owner.get("/audit", params={"action": "action."}).json()} <= {
        "action.proposed",
        "action.approved",
        "action.executed",
        "action.verified",
        "action.refused",
        "action.blocked",
        "action.rejected",
    }
    [task] = [t for t in owner.get("/tasks").json() if t["task_id"] == done["outcome"]["task_id"]]
    assert task["conversation_id"] == "trace-1"
    checks = api.viewer.get("/checks").json()
    assert checks and {"model", "test", "status"} <= set(checks[0])
