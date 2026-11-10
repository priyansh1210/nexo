"""Runs the data pipeline: land new records in `raw`, then build the warehouse with dbt.

`raw` is append-only, so everything downstream can be rebuilt from it at any time (replay).
"""

import json
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import psycopg
from dbt.cli.main import dbtRunner
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from data.connectors import Connector, EventLog, FileSnapshot, HelpdeskApi

DBT_DIR = Path(__file__).parent.parent / "dbt"
SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

# How often each source is expected to sync. A source is stale after twice this interval.
EXPECTED_EVERY = {
    "crm": "24 hours",
    "product_events": "1 hour",
    "support_tickets": "1 hour",
    "billing": "24 hours",
    "documents": "24 hours",
}


def connectors(data_dir: Path, helpdesk) -> list[Connector]:
    return [
        FileSnapshot(
            "crm",
            {"crm_accounts": data_dir / "accounts.csv", "crm_contacts": data_dir / "contacts.csv"},
        ),
        EventLog(data_dir / "events.jsonl"),
        HelpdeskApi(helpdesk),
        FileSnapshot("billing", {"billing_invoices": data_dir / "invoices.csv"}),
        FileSnapshot("documents", {"documents": data_dir / "documents.jsonl"}),
    ]


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


def sync(conn: psycopg.Connection, sources: list[Connector]) -> dict[str, int | str]:
    """Land new records from each source. Returns records landed, or the error, per source."""
    conn.execute(SCHEMA_SQL)
    results: dict[str, int | str] = {}
    for connector in sources:
        source = connector.source
        stalled = conn.execute(
            "insert into meta.sources (source, expected_every) values (%s, %s::interval) "
            "on conflict (source) do update set expected_every = excluded.expected_every "
            "returning stalled_since",
            (source, EXPECTED_EVERY[source]),
        ).fetchone()[0]
        if stalled:
            results[source] = "stalled"
            continue

        started, batch_id = datetime.now(UTC), uuid.uuid4()
        try:
            # One transaction per source: records, cursor and the run row land together or not at all.
            with conn.transaction():
                landed = 0
                for stream in connector.streams:
                    table = sql.Identifier("raw", stream)
                    conn.execute(
                        sql.SQL(
                            "create table if not exists {} (payload jsonb not null, "
                            "_source text not null, _batch_id uuid not null, "
                            "_ingested_at timestamptz not null default now())"
                        ).format(table)
                    )
                    row = conn.execute(
                        "select cursor from meta.cursors where source = %s and stream = %s",
                        (source, stream),
                    ).fetchone()
                    batch = connector.read(stream, row[0] if row else None)
                    copy_sql = sql.SQL("copy {} (payload, _source, _batch_id) from stdin")
                    with conn.cursor().copy(copy_sql.format(table)) as copy:
                        for record in batch.records:
                            copy.write_row((Jsonb(record), source, batch_id))
                    if batch.cursor is not None:
                        conn.execute(
                            "insert into meta.cursors values (%s, %s, %s) "
                            "on conflict (source, stream) do update set cursor = excluded.cursor",
                            (source, stream, batch.cursor),
                        )
                    landed += len(batch.records)
                conn.execute(
                    "insert into meta.sync_runs (source, batch_id, status, records, started_at) "
                    "values (%s, %s, 'success', %s, %s)",
                    (source, batch_id, landed, started),
                )
            results[source] = landed
        except Exception as error:  # noqa: BLE001 - one failing source must not stop the others
            message = f"{type(error).__name__}: {error}"[:500]
            conn.execute(
                "insert into meta.sync_runs (source, batch_id, status, error, started_at) "
                "values (%s, %s, 'failed', %s, %s)",
                (source, batch_id, message, started),
            )
            results[source] = f"failed: {message}"
    return results


def build(
    conn: psycopg.Connection, full_refresh: bool = False, replay: tuple[date, date] | None = None
) -> bool:
    """Run dbt (models, snapshots, tests) and record every test result. True when all passed."""
    info = conninfo_to_dict(os.environ["DATABASE_URL"])
    for key in ("host", "port", "user", "password", "dbname"):
        os.environ[f"NEXO_PG_{key.upper()}"] = str(info.get(key) or "")
    args = ["build", "--quiet", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    args += ["--target-path", str(DBT_DIR / "target"), "--log-path", str(DBT_DIR / "logs")]
    if full_refresh:
        args.append("--full-refresh")
    if replay:
        days = {"replay_from": replay[0].isoformat(), "replay_to": replay[1].isoformat()}
        args += ["--vars", json.dumps(days)]

    outcome = dbtRunner().invoke(args)
    if outcome.result is None:  # dbt could not even start the build, for example a parse error
        raise RuntimeError(f"dbt build did not run: {outcome.exception}")

    checks = []
    for result in outcome.result.results:
        node = result.node
        if node.resource_type in ("test", "unit_test"):
            # The model a test guards: generic tests name it, unit tests name it differently, and a
            # hand-written test only has the relations it reads.
            parent = (
                getattr(node, "attached_node", None)
                or getattr(node, "tested_node_unique_id", None)
                or next(iter(node.depends_on.nodes), "")
            )
            checks.append((parent.split(".")[-1], node.name, str(result.status), result.failures))
    with conn.transaction():
        conn.execute("delete from meta.check_results")
        with conn.cursor() as cursor:
            cursor.executemany(
                "insert into meta.check_results (model, test, status, failures) values (%s, %s, %s, %s)",
                checks,
            )
    return outcome.success


def failed_sources(synced: dict[str, int | str]) -> list[str]:
    return [source for source, outcome in synced.items() if str(outcome).startswith("failed")]


def refresh() -> tuple[dict[str, int | str], bool]:
    """One full pipeline run with the settings from the environment."""
    data_dir = Path(os.environ.get("NEXO_DATA_DIR", "data/synthetic/out"))
    base_url = os.environ.get("MOCK_SOURCES_URL", "http://localhost:8001")
    with connect() as conn, httpx.Client(base_url=base_url, timeout=10) as helpdesk:
        synced = sync(conn, connectors(data_dir, helpdesk))
        return synced, build(conn)


def stall(conn: psycopg.Connection, source: str, hours: float) -> None:
    """Demo and test hook: make a source look as if its pipeline stopped `hours` ago."""
    _set_stalled(conn, source, "now() - make_interval(secs => %s)", (hours * 3600,))


def resume(conn: psycopg.Connection, source: str) -> None:
    _set_stalled(conn, source, "null", ())


def _set_stalled(conn: psycopg.Connection, source: str, value: str, params: tuple) -> None:
    query = f"update meta.sources set stalled_since = {value} where source = %s"
    if conn.execute(query, (*params, source)).rowcount == 0:
        raise ValueError(f"unknown source {source!r}; known: {sorted(EXPECTED_EVERY)}")
