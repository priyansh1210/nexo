"""Connectors pull records out of a source system. The sync runner lands them in `raw`.

To add a source, write a class with these three members and register it in
`data/pipelines/runner.py`. A connector never writes to the database and never stores its own
cursor: the runner saves the records and the new cursor in one transaction, so a crash can neither
lose records nor load them twice.
"""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Batch:
    records: list[dict]
    cursor: str | None  # where to resume next time; saved only after the records have landed


class Connector(Protocol):
    source: str  # freshness is tracked per source
    streams: tuple[str, ...]  # each stream fills the raw table of the same name

    def read(self, stream: str, cursor: str | None) -> Batch: ...


class FileSnapshot:
    """A whole-file export, CSV or JSONL. It is re-read only when its content changes."""

    def __init__(self, source: str, files: dict[str, Path]):
        self.source, self.files, self.streams = source, files, tuple(files)

    def read(self, stream: str, cursor: str | None) -> Batch:
        path = self.files[stream]
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest == cursor:
            return Batch([], cursor)
        text = content.decode("utf-8")
        if path.suffix == ".csv":
            return Batch(list(csv.DictReader(io.StringIO(text))), digest)
        return Batch([json.loads(line) for line in text.splitlines() if line.strip()], digest)


class EventLog:
    """An append-only JSONL event log. The cursor is the number of lines already read."""

    source = "product_events"
    streams = ("product_events",)
    required = frozenset({"workspace_id", "user_id", "name", "occurred_at"})

    def __init__(self, path: Path):
        self.path = path

    def read(self, stream: str, cursor: str | None) -> Batch:
        start = int(cursor or 0)
        # shortcut: reads the whole file to skip old lines, fine for a demo log; keep a byte offset
        # when logs reach gigabytes.
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records = []
        for number, line in enumerate(lines[start:], start + 1):
            record = json.loads(line)
            if missing := self.required - record.keys():
                # shortcut: one bad line stops this source so nothing is silently dropped; add a
                # dead-letter table when real event sources are connected.
                raise ValueError(f"{self.path.name} line {number} is missing {sorted(missing)}")
            records.append(record)
        return Batch(records, str(len(lines)))


class HelpdeskApi:
    """Tickets from the helpdesk API, changed since the last read.

    Times are whole seconds, so the API is asked from the newest second already seen, inclusive: a
    ticket changed later in that same second is not missed. The cursor also holds the tickets
    already landed at that second, which are skipped. (The same ticket changed twice within one
    second is still read once.)
    """

    source = "support_tickets"
    streams = ("support_tickets",)

    def __init__(self, client):
        self.client = client  # an httpx.Client pointed at the helpdesk

    def read(self, stream: str, cursor: str | None) -> Batch:
        # An older cursor is a bare time: its tickets are read once more, then the new form is used.
        seen = json.loads(cursor) if (cursor or "").startswith("{") else {"at": cursor, "ids": []}
        response = self.client.get("/helpdesk/tickets", params={"updated_since": seen["at"] or ""})
        response.raise_for_status()
        tickets = [
            t
            for t in response.json()
            if not (t["updated_at"] == seen["at"] and t["ticket_id"] in seen["ids"])
        ]
        if not tickets:
            return Batch([], cursor)
        at = max(t["updated_at"] for t in tickets)
        ids = {t["ticket_id"] for t in tickets if t["updated_at"] == at}
        ids |= set(seen["ids"]) if at == seen["at"] else set()
        return Batch(tickets, json.dumps({"at": at, "ids": sorted(ids)}))
