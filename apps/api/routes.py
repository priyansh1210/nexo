"""Workspace routes: accounts, notes, tasks, data freshness and the audit log.

Account data comes from the `marts` schema that dbt builds; every response that carries it also
says how fresh each source is and whether the warehouse checks passed. Notes and tasks are the
application's own records, and every write to them adds an audit row in the same transaction.
"""

from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from apps.api.auth import Csm, Viewer
from apps.api.db import Db, audit

router = APIRouter()

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Freshness(BaseModel):
    source: str
    status: Literal["fresh", "stale"]
    last_updated: datetime | None
    expected_every_seconds: int
    is_stalled: bool
    rejected_last_day: int  # records that could not be read lately; the totals may be low


class Checks(BaseModel):
    passed: int
    failed: int
    failed_models: list[str]  # metrics built on these models should not be trusted


class Account(BaseModel):
    account_id: str
    name: str
    owner_name: str
    owner_email: str
    plan: str
    seats: int
    arr_usd: int
    contract_start: date
    renewal_date: date
    open_tickets: int
    # None means unknown, never zero: usage_status says why.
    usage_change: float | None
    usage_status: Literal["ok", "no_linked_workspace", "no_recent_usage", "no_baseline"]
    usage_as_of: date | None
    stale_high_tickets: int
    overdue_invoices: int
    risk_usage_drop: bool
    risk_stale_ticket: bool
    risk_overdue_invoice: bool
    is_at_risk: bool


class AccountList(BaseModel):
    accounts: list[Account]
    freshness: list[Freshness]
    checks: Checks


class Usage(BaseModel):
    as_of_day: date
    events_last_30d: int
    events_prior_30d: int
    active_users_last_30d: int
    active_users_prior_30d: int


class FeatureUsage(BaseModel):
    feature: str
    events_last_30d: int
    events_prior_30d: int
    usage_change: float | None  # None when the feature had no use in the prior 30 days
    users_last_30d: int
    users_prior_30d: int


class DailyUsage(BaseModel):
    day: date
    feature: str
    events: int


class UsageByFeature(BaseModel):
    account_id: str
    # Anything but "ok" means there is no usage to show, and why; it is never zero usage.
    usage_status: Literal["ok", "no_linked_workspace", "no_recent_usage", "no_baseline"]
    as_of_day: date | None
    features: list[FeatureUsage]
    daily: list[DailyUsage]  # the 60 days up to as_of_day, for a chart
    freshness: list[Freshness]
    checks: Checks


class Onboarding(BaseModel):
    kickoff_at: datetime | None
    admin_setup_at: datetime | None
    team_invited_at: datetime | None
    data_import_at: datetime | None
    go_live_at: datetime | None
    steps_completed: int
    is_complete: bool


class Ticket(BaseModel):
    ticket_id: str
    subject: str
    severity: str
    status: str
    is_open: bool
    age_days: int
    created_at: datetime
    updated_at: datetime
    requester_email: str | None


class Contact(BaseModel):
    contact_id: str
    name: str
    email: str
    role: str
    is_active: bool


class AccountProfile(BaseModel):
    account: Account
    usage: Usage | None
    onboarding: Onboarding | None
    tickets: list[Ticket]
    contacts: list[Contact]
    freshness: list[Freshness]
    checks: Checks


class Note(BaseModel):
    note_id: int
    account_id: str
    body: str
    author_name: str
    created_at: datetime


class NoteIn(BaseModel):
    body: Text


class EmailIn(BaseModel):
    to_email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    subject: Title
    body: Text
    ticket_id: str | None = None  # the ticket the email is about


class Task(BaseModel):
    task_id: int
    account_id: str
    title: str
    detail: str
    status: Literal["open", "done"]
    assignee_email: str | None
    assignee_name: str | None
    due_on: date | None
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class TaskIn(BaseModel):
    title: Title
    detail: str = Field(default="", max_length=5000)
    assignee_email: str | None = None
    due_on: date | None = None


class TaskChange(BaseModel):
    status: Literal["open", "done"] | None = None
    assignee_email: str | None = None


class AuditEvent(BaseModel):
    event_id: int
    at: datetime
    actor_email: str | None
    actor_name: str | None
    action: str
    account_id: str | None
    target_type: str | None
    target_id: str | None
    detail: dict


ACCOUNTS = """
    select a.account_id, a.name, a.owner_name, a.owner_email, a.plan, a.seats, a.arr_usd,
           a.contract_start, a.renewal_date,
           (select count(*) from marts.fct_tickets t where t.account_id = a.account_id and t.is_open)
               as open_tickets,
           h.usage_change, h.usage_status, h.usage_as_of, h.stale_high_tickets, h.overdue_invoices,
           h.risk_usage_drop, h.risk_stale_ticket, h.risk_overdue_invoice, h.is_at_risk
    from marts.dim_account a
    join marts.account_health h on h.account_id = a.account_id
"""
TASKS = """
    select t.task_id, t.account_id, t.title, t.detail, t.status, t.due_on, t.created_at, t.updated_at,
           assignee.email as assignee_email, assignee.name as assignee_name,
           creator.name as created_by_name
    from app.tasks t
    join app.users creator on creator.user_id = t.created_by
    left join app.users assignee on assignee.user_id = t.assignee_id
"""


def data_status(db: psycopg.Connection) -> dict:
    """How far the data behind an answer can be trusted: source freshness and warehouse checks."""
    freshness = db.execute(
        "select source, status, last_updated, is_stalled, rejected_last_day, "
        "extract(epoch from expected_every)::int as expected_every_seconds "
        "from meta.source_freshness order by source"
    ).fetchall()
    checks = db.execute(
        "select count(*) filter (where status = 'pass') as passed, "
        "count(*) filter (where status in ('fail', 'error')) as failed, "
        "coalesce(array_agg(distinct model) filter (where status in ('fail', 'error')), '{}') as failed_models "
        "from meta.check_results"
    ).fetchone()
    return {"freshness": freshness, "checks": checks}


def require_account(db: psycopg.Connection, account_id: str) -> None:
    if not db.execute(
        "select 1 from marts.dim_account where account_id = %s", (account_id,)
    ).fetchone():
        raise HTTPException(404, f"No account {account_id}")


def user_id_for(db: psycopg.Connection, email: str | None) -> int | None:
    if email is None:
        return None
    user = db.execute(
        "select user_id from app.users where email = %s", (email.strip().lower(),)
    ).fetchone()
    if not user:
        raise HTTPException(422, f"No user with the email {email}")
    return user["user_id"]


@router.get("/accounts")
def list_accounts(db: Db, user: Viewer) -> AccountList:
    accounts = db.execute(ACCOUNTS + " order by a.renewal_date, a.name").fetchall()
    return AccountList(accounts=accounts, **data_status(db))


@router.get("/accounts/{account_id}")
def get_account(account_id: str, db: Db, user: Viewer) -> AccountProfile:
    account = db.execute(ACCOUNTS + " where a.account_id = %s", (account_id,)).fetchone()
    if not account:
        raise HTTPException(404, f"No account {account_id}")
    by_account = " where account_id = %s"
    return AccountProfile(
        account=account,
        usage=db.execute(
            "select * from marts.fct_usage_trend" + by_account, (account_id,)
        ).fetchone(),
        onboarding=db.execute(
            "select * from marts.fct_onboarding" + by_account, (account_id,)
        ).fetchone(),
        tickets=db.execute(
            "select * from marts.fct_tickets"
            + by_account
            + " order by is_open desc, created_at desc limit 50",
            (account_id,),
        ).fetchall(),
        contacts=db.execute(
            "select * from marts.dim_contact" + by_account + " order by role", (account_id,)
        ).fetchall(),
        **data_status(db),
    )


@router.get("/accounts/{account_id}/usage")
def get_usage_by_feature(account_id: str, db: Db, user: Viewer) -> UsageByFeature:
    health = db.execute(
        "select usage_status, usage_as_of from marts.account_health where account_id = %s",
        (account_id,),
    ).fetchone()
    if not health:
        raise HTTPException(404, f"No account {account_id}")
    features = db.execute(
        "select * from marts.fct_usage_by_feature where account_id = %s "
        "order by events_last_30d desc, feature",
        (account_id,),
    ).fetchall()
    daily = db.execute(
        "select day, feature, events from marts.fct_usage_daily "
        "where account_id = %s and day > %s::date - 60 order by day, feature",
        (account_id, health["usage_as_of"]),
    ).fetchall()
    return UsageByFeature(
        account_id=account_id,
        usage_status=health["usage_status"],
        as_of_day=health["usage_as_of"],
        features=features,
        daily=daily,
        **data_status(db),
    )


@router.get("/accounts/{account_id}/notes")
def list_notes(account_id: str, db: Db, user: Viewer) -> list[Note]:
    require_account(db, account_id)
    return db.execute(
        "select n.note_id, n.account_id, n.body, n.created_at, u.name as author_name "
        "from app.notes n join app.users u on u.user_id = n.author_id "
        "where n.account_id = %s order by n.created_at desc, n.note_id desc",
        (account_id,),
    ).fetchall()


@router.post("/accounts/{account_id}/notes", status_code=201)
def add_note(account_id: str, note: NoteIn, db: Db, user: Csm) -> Note:
    require_account(db, account_id)
    created = db.execute(
        "insert into app.notes (account_id, author_id, body) values (%s, %s, %s) "
        "returning note_id, account_id, body, created_at",
        (account_id, user["user_id"], note.body),
    ).fetchone()
    audit(db, user, "note.created", account_id=account_id, target=("note", created["note_id"]))
    return Note(**created, author_name=user["name"])


@router.get("/accounts/{account_id}/tasks")
def list_account_tasks(account_id: str, db: Db, user: Viewer) -> list[Task]:
    require_account(db, account_id)
    return db.execute(
        TASKS + " where t.account_id = %s order by t.created_at desc", (account_id,)
    ).fetchall()


@router.post("/accounts/{account_id}/tasks", status_code=201)
def add_task(account_id: str, task: TaskIn, db: Db, user: Csm) -> Task:
    require_account(db, account_id)
    task_id = db.execute(
        "insert into app.tasks (account_id, title, detail, assignee_id, created_by, due_on) "
        "values (%s, %s, %s, %s, %s, %s) returning task_id",
        (
            account_id,
            task.title,
            task.detail,
            user_id_for(db, task.assignee_email),
            user["user_id"],
            task.due_on,
        ),
    ).fetchone()["task_id"]
    audit(
        db,
        user,
        "task.created",
        account_id=account_id,
        target=("task", task_id),
        detail={"title": task.title, "assignee_email": task.assignee_email},
    )
    return db.execute(TASKS + " where t.task_id = %s", (task_id,)).fetchone()


@router.get("/tasks")
def list_tasks(db: Db, user: Viewer, mine: bool = False) -> list[Task]:
    newest_open_first = " order by t.status desc, t.created_at desc"
    if mine:
        return db.execute(
            TASKS + " where t.assignee_id = %s" + newest_open_first, (user["user_id"],)
        ).fetchall()
    return db.execute(TASKS + newest_open_first).fetchall()


@router.patch("/tasks/{task_id}")
def change_task(task_id: int, change: TaskChange, db: Db, user: Csm) -> Task:
    fields = change.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Give a status, an assignee_email, or both")
    before = db.execute(TASKS + " where t.task_id = %s for update of t", (task_id,)).fetchone()
    if not before:
        raise HTTPException(404, f"No task {task_id}")

    status = fields.get("status") or before["status"]
    assignee_email = fields.get("assignee_email", before["assignee_email"])
    db.execute(
        "update app.tasks set status = %s, assignee_id = %s, updated_at = now() where task_id = %s",
        (status, user_id_for(db, assignee_email), task_id),
    )
    after = {"status": status, "assignee_email": assignee_email}
    audit(
        db,
        user,
        "task.updated",
        account_id=before["account_id"],
        target=("task", task_id),
        detail={"before": {key: before[key] for key in after}, "after": after},
    )
    return db.execute(TASKS + " where t.task_id = %s", (task_id,)).fetchone()


@router.get("/freshness")
def get_freshness(db: Db, user: Viewer) -> list[Freshness]:
    return data_status(db)["freshness"]


@router.get("/audit")
def list_audit(
    db: Db,
    user: Csm,
    account_id: str | None = None,
    action: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEvent]:
    return db.execute(
        "select e.event_id, e.at, e.action, e.account_id, e.target_type, e.target_id, e.detail, "
        "u.email as actor_email, u.name as actor_name "
        "from audit.events e left join app.users u on u.user_id = e.actor_id "
        "where (%(account_id)s::text is null or e.account_id = %(account_id)s) "
        "and (%(action)s::text is null or e.action = %(action)s) "
        "order by e.event_id desc limit %(limit)s",
        {"account_id": account_id, "action": action, "limit": limit},
    ).fetchall()
