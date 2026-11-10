"""Stand-in for the live source systems: the CRM, the helpdesk and the product's event log.

It owns the demo's source data. On first start it writes the synthetic files that the pipelines
ingest, and it serves the same records over HTTP so actions can re-read them just before a write.
"""

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from data.synthetic.generate import generate, write


class TicketChange(BaseModel):
    status: Literal["open", "pending", "solved"]


def load() -> dict[str, list[dict]]:
    """Generate the source data once per data directory, and the same data on every restart."""
    seed, out = int(os.environ.get("NEXO_SEED", "7")), os.environ.get("NEXO_DATA_DIR")
    if not out:
        return generate(seed)
    # The data is anchored to the day it was first generated; that day is remembered here so a
    # restart on a later day serves the records the warehouse already holds.
    marker = Path(out) / "as_of.txt"
    if marker.exists():
        return generate(seed, date.fromisoformat(marker.read_text().strip()))
    today = date.today()
    data = generate(seed, today)
    write(data, Path(out))
    marker.write_text(today.isoformat())
    return data


def create_app(data: dict[str, list[dict]]) -> FastAPI:
    app = FastAPI(title="Nexo mock sources")
    # shortcut: changes live in memory and reset on restart; persist them when a demo must survive one.
    accounts = {a["account_id"]: a for a in data["accounts"]}
    tickets = {t["ticket_id"]: dict(t) for t in data["tickets"]}

    def find(table: dict, key: str) -> dict:
        if key not in table:
            raise HTTPException(404, f"{key} not found")
        return table[key]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/crm/accounts/{account_id}")
    def get_account(account_id: str) -> dict:
        return find(accounts, account_id)

    @app.get("/crm/accounts/{account_id}/contacts")
    def get_contacts(account_id: str) -> list[dict]:
        find(accounts, account_id)
        return [c for c in data["contacts"] if c["account_id"] == account_id]

    @app.get("/helpdesk/tickets")
    def list_tickets(updated_since: str = "") -> list[dict]:
        """Tickets changed after `updated_since`; all of them when it is empty."""
        return [t for t in tickets.values() if t["updated_at"] > updated_since]

    @app.get("/helpdesk/tickets/{ticket_id}")
    def get_ticket(ticket_id: str) -> dict:
        return find(tickets, ticket_id)

    @app.patch("/helpdesk/tickets/{ticket_id}")
    def change_ticket(ticket_id: str, change: TicketChange) -> dict:
        """Simulates the source system changing after the warehouse snapshot was taken."""
        ticket = find(tickets, ticket_id)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        ticket.update(status=change.status, updated_at=now)
        ticket["solved_at"] = now if change.status == "solved" else None
        return ticket

    return app


app = create_app(load())
