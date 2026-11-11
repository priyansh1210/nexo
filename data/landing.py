"""Landing records in the append-only `raw` schema.

Shared by the two ways data arrives: the pipeline's connectors, which pull from a source, and the
API's ingest routes, which a source pushes to. Both write the same envelope and the same run row,
so freshness and replay do not care which way a record came in.
"""

import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

SCHEMA_SQL = (Path(__file__).parent / "pipelines" / "schema.sql").read_text(encoding="utf-8")

# How often each source is expected to deliver. A source is stale after twice this interval.
EXPECTED_EVERY = {
    "crm": "24 hours",
    "product_events": "1 hour",
    "support_tickets": "1 hour",
    "billing": "24 hours",
    "documents": "24 hours",
}


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create the raw, meta and vec tables if missing. Safe when several services start at once."""
    # "create ... if not exists" is not safe against itself: two services running it at the same
    # moment can both decide to create and one fails. The lock makes them take turns.
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(727276)")
        conn.execute(SCHEMA_SQL)


def register_source(conn: psycopg.Connection, source: str) -> datetime | None:
    """Make sure the source is known to the freshness view. Returns when it was stalled, if it is."""
    return (
        conn.cursor(row_factory=tuple_row)
        .execute(
            "insert into meta.sources (source, expected_every) values (%s, %s::interval) "
            "on conflict (source) do update set expected_every = excluded.expected_every "
            "returning stalled_since",
            (source, EXPECTED_EVERY[source]),
        )
        .fetchone()[0]
    )


def land(
    conn: psycopg.Connection,
    source: str,
    stream: str,
    records: list[dict],
    batch_id: uuid.UUID,
    origin: str | None = None,
) -> int:
    """Append records to raw.<stream>. `stream` must be a name from code, never from a request.

    `_source` records where each row came from: the source name when pulled, or who pushed it.
    """
    table = sql.Identifier("raw", stream)
    conn.execute(
        sql.SQL(
            "create table if not exists {} (payload jsonb not null, _source text not null, "
            "_batch_id uuid not null, _ingested_at timestamptz not null default now())"
        ).format(table)
    )
    copy_rows = sql.SQL("copy {} (payload, _source, _batch_id) from stdin").format(table)
    with conn.cursor().copy(copy_rows) as copy:
        for record in records:
            copy.write_row((Jsonb(record), origin or source, batch_id))
    return len(records)


def record_run(
    conn: psycopg.Connection,
    source: str,
    batch_id: uuid.UUID,
    started_at: datetime,
    *,
    records: int = 0,
    error: str | None = None,
) -> None:
    """One row per delivery attempt. The freshness view reads the successful ones."""
    conn.execute(
        "insert into meta.sync_runs (source, batch_id, status, records, error, started_at) "
        "values (%s, %s, %s, %s, %s, %s)",
        (source, batch_id, "failed" if error else "success", records, error, started_at),
    )
