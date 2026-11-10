"""Stand-in for the live CRM and helpdesk APIs.

Actions re-read records here just before they write, so a stale analytical snapshot cannot cause a
wrong update. It serves the same synthetic data the pipelines ingest.
"""

import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from data.synthetic.generate import generate

app = FastAPI(title="Nexo mock sources")

# shortcut: state lives in memory and resets on restart; persist it when a demo must survive one.
_data = generate(int(os.environ.get("NEXO_SEED", "7")))
accounts = {a["account_id"]: a for a in _data["accounts"]}
tickets = {t["ticket_id"]: t for t in _data["tickets"]}
contacts = _data["contacts"]


class TicketChange(BaseModel):
    status: Literal["open", "pending", "solved"]


def _find(table: dict, key: str) -> dict:
    if key not in table:
        raise HTTPException(404, f"{key} not found")
    return table[key]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/crm/accounts/{account_id}")
def get_account(account_id: str) -> dict:
    return _find(accounts, account_id)


@app.get("/crm/accounts/{account_id}/contacts")
def get_contacts(account_id: str) -> list[dict]:
    _find(accounts, account_id)
    return [c for c in contacts if c["account_id"] == account_id]


@app.get("/helpdesk/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    return _find(tickets, ticket_id)


@app.patch("/helpdesk/tickets/{ticket_id}")
def change_ticket(ticket_id: str, change: TicketChange) -> dict:
    """Simulates the source system changing after the warehouse snapshot was taken."""
    ticket = _find(tickets, ticket_id)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ticket.update(status=change.status, updated_at=now)
    ticket["solved_at"] = now if change.status == "solved" else None
    return ticket
