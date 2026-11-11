"""Pushing data in: API keys for machines, and the three ingest routes.

A product backend or a helpdesk webhook signs in with an API key; an admin can also push while
signed in. Everything is validated here, at the edge, so a malformed record is refused with a clear
error instead of landing in `raw` and breaking the warehouse build for everyone. What is accepted
lands exactly like pulled data and shows up in the warehouse after the next pipeline run.
"""

import csv
import hashlib
import io
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from apps.api.auth import Admin, current_user
from apps.api.db import Db, audit
from data.landing import land, record_run, register_source

router = APIRouter(tags=["ingest"])

MAX_CSV_BYTES = 5 * 1024 * 1024
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ApiKeyIn(BaseModel):
    name: Name


class ApiKey(BaseModel):
    key_id: int
    name: str
    created_by_name: str
    created_at: datetime
    revoked_at: datetime | None


class NewApiKey(ApiKey):
    key: str  # shown this once; only its hash is kept


class Landed(BaseModel):
    landed: int
    batch_id: uuid.UUID


class EventIn(BaseModel):
    event_id: Name | None = None  # without one, the event is identified by a hash of its content
    workspace_id: Name
    user_id: Name
    name: Name
    occurred_at: AwareDatetime  # must carry a time zone: a bare timestamp is ambiguous
    properties: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=50
    )

    @field_validator("occurred_at")
    @classmethod
    def not_in_the_future(cls, value: datetime) -> datetime:
        # The usage windows end on the newest event day, so a single event dated far ahead would
        # empty every account's trend.
        if value > datetime.now(UTC) + timedelta(days=1):
            raise ValueError("occurred_at is in the future")
        return value


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=5000)


class TicketIn(BaseModel):
    ticket_id: Name
    org_id: Name
    requester_email: str | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    body: str = Field(default="", max_length=20000)
    severity: Literal["low", "normal", "high", "urgent"]
    status: Literal["open", "pending", "solved"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    solved_at: AwareDatetime | None = None


class TicketBatch(BaseModel):
    tickets: list[TicketIn] = Field(min_length=1, max_length=1000)


class CrmAccount(BaseModel):
    account_id: Name
    name: Name
    domain: str = ""
    owner_name: Name
    owner_email: Name
    plan: Name
    seats: int = Field(ge=0)
    arr_usd: int = Field(ge=0)
    term_months: int = Field(ge=1)
    contract_start: date
    renewal_date: date
    workspace_id: str = ""
    support_org_id: str = ""


class CrmContact(BaseModel):
    contact_id: Name
    account_id: Name
    name: Name
    email: Name
    role: Name
    is_active: bool = True


CRM_FILES = {"accounts": ("crm_accounts", CrmAccount), "contacts": ("crm_contacts", CrmContact)}


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def pusher(request: Request, db: Db) -> dict:
    """Who is pushing: a valid API key, or an admin who is signed in."""
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer":
        found = db.execute(
            "select key_id, name from app.api_keys where key_hash = %s and revoked_at is null",
            (_key_hash(key.strip()),),
        ).fetchone()
        if not found:
            raise HTTPException(401, "Unknown or revoked API key")
        # A key is not a user, so its audit rows have no actor; the key is named in their detail.
        return {"user_id": None, "label": f"api key {found['name']}", "key_id": found["key_id"]}
    user = current_user(request, db)
    if user["role"] != "admin":
        raise HTTPException(403, "Pushing data needs an API key or the admin role")
    return {"user_id": user["user_id"], "label": user["email"], "key_id": None}


Pusher = Annotated[dict, Depends(pusher)]


def push(
    db: psycopg.Connection, source: str, stream: str, records: list[dict], pushed_by: dict
) -> Landed:
    """Land a validated batch, count it as a delivery from its source, and audit it."""
    started, batch_id = datetime.now(UTC), uuid.uuid4()
    # A stalled source still accepts pushes, so nothing a real system sends is lost; stalling only
    # stops the pull side and holds the freshness reading.
    register_source(db, source)
    landed = land(db, source, stream, records, batch_id, origin=f"push by {pushed_by['label']}")
    record_run(db, source, batch_id, started, records=landed)
    audit(
        db,
        pushed_by,
        f"ingest.{stream}",
        target=("batch", batch_id),
        detail={
            "pushed_by": pushed_by["label"],
            "api_key_id": pushed_by["key_id"],
            "records": landed,
        },
    )
    return Landed(landed=landed, batch_id=batch_id)


@router.post("/api-keys", status_code=201)
def create_api_key(new: ApiKeyIn, db: Db, user: Admin) -> NewApiKey:
    key = "nexo_" + secrets.token_urlsafe(32)
    created = db.execute(
        "insert into app.api_keys (name, key_hash, created_by) values (%s, %s, %s) "
        "returning key_id, name, created_at, revoked_at",
        (new.name, _key_hash(key), user["user_id"]),
    ).fetchone()
    audit(
        db,
        user,
        "api_key.created",
        target=("api_key", created["key_id"]),
        detail={"name": new.name},
    )
    return NewApiKey(**created, created_by_name=user["name"], key=key)


@router.get("/api-keys")
def list_api_keys(db: Db, user: Admin) -> list[ApiKey]:
    return db.execute(
        "select k.key_id, k.name, k.created_at, k.revoked_at, u.name as created_by_name "
        "from app.api_keys k join app.users u on u.user_id = k.created_by order by k.key_id"
    ).fetchall()


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: int, db: Db, user: Admin) -> None:
    revoked = db.execute(
        "update app.api_keys set revoked_at = now() where key_id = %s and revoked_at is null returning name",
        (key_id,),
    ).fetchone()
    if not revoked:
        raise HTTPException(404, f"No active API key {key_id}")
    audit(db, user, "api_key.revoked", target=("api_key", key_id), detail={"name": revoked["name"]})


@router.post("/ingest/events", status_code=202)
def ingest_events(batch: EventBatch, db: Db, pushed_by: Pusher) -> Landed:
    records = [event.model_dump(mode="json", exclude_none=True) for event in batch.events]
    return push(db, "product_events", "product_events", records, pushed_by)


@router.post("/ingest/tickets", status_code=202)
def ingest_tickets(batch: TicketBatch, db: Db, pushed_by: Pusher) -> Landed:
    records = [ticket.model_dump(mode="json") for ticket in batch.tickets]
    return push(db, "support_tickets", "support_tickets", records, pushed_by)


@router.post("/import/crm/{kind}", status_code=202)
def import_crm(
    kind: Literal["accounts", "contacts"],
    content: Annotated[bytes, Body(media_type="text/csv")],
    db: Db,
    pushed_by: Pusher,
) -> Landed:
    """Import a CRM export. The body is the CSV file itself. One bad row refuses the whole file."""
    # shortcut: the size is checked after the body is read; cap request size at the reverse proxy
    # before exposing this to the internet.
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(413, f"The file is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB")
    try:
        text = content.decode("utf-8-sig")  # utf-8-sig also accepts the mark Excel adds
    except UnicodeDecodeError:
        raise HTTPException(422, "The file is not UTF-8 text") from None

    stream, row_model = CRM_FILES[kind]
    records, problems = [], []
    for line, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):  # line 1 is the header
        try:
            records.append(row_model.model_validate(row).model_dump(mode="json"))
        except ValidationError as error:
            problems += [
                f"line {line}, {issue['loc'][0]}: {issue['msg']}" for issue in error.errors()
            ]
    if problems or not records:
        raise HTTPException(
            422, {"message": "Nothing was imported.", "problems": problems[:20] or ["no rows"]}
        )
    return push(db, "crm", stream, records, pushed_by)
