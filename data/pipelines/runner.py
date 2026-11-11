"""Runs the data pipeline: land new records in `raw`, then build the warehouse with dbt.

`raw` is append-only, so everything downstream can be rebuilt from it at any time (replay).
"""

import json
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import psycopg
from dbt.cli.main import dbtRunner

from data.connectors import Connector, EventLog, FileSnapshot, HelpdeskApi
from data.embeddings import embed_documents
from data.landing import EXPECTED_EVERY, ensure_schema, land, record_run, register_source

DBT_DIR = Path(__file__).parent.parent / "dbt"
RUN_LOCK = 727277  # held by sync() and build(), so a second run waits for the first


@contextmanager
def one_run_at_a_time(conn: psycopg.Connection):
    # Two builds at once would each rebuild the same usage days and count them twice, and share
    # dbt's temporary table names; two syncs would land the same records twice. `make sync` during
    # the hourly run is enough to cause it.
    conn.execute("select pg_advisory_lock(%s)", (RUN_LOCK,))
    try:
        yield
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (RUN_LOCK,))


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
    ensure_schema(conn)
    with one_run_at_a_time(conn):
        return _sync(conn, sources)


def _sync(conn: psycopg.Connection, sources: list[Connector]) -> dict[str, int | str]:
    results: dict[str, int | str] = {}
    for connector in sources:
        source = connector.source
        if register_source(conn, source):
            results[source] = "stalled"
            continue

        started, batch_id = datetime.now(UTC), uuid.uuid4()
        try:
            # One transaction per source: records, cursor and the run row land together or not at all.
            with conn.transaction():
                landed = rejected = 0
                for stream in connector.streams:
                    row = conn.execute(
                        "select cursor from meta.cursors where source = %s and stream = %s",
                        (source, stream),
                    ).fetchone()
                    batch = connector.read(stream, row[0] if row else None)
                    landed += land(conn, source, stream, batch.records, batch_id)
                    for bad in batch.rejected:
                        conn.execute(
                            "insert into meta.dead_letters (source, stream, batch_id, record, error) "
                            "values (%s, %s, %s, %s, %s)",
                            (source, stream, batch_id, bad["record"], bad["error"]),
                        )
                    rejected += len(batch.rejected)
                    if batch.cursor is not None:
                        conn.execute(
                            "insert into meta.cursors values (%s, %s, %s) "
                            "on conflict (source, stream) do update set cursor = excluded.cursor",
                            (source, stream, batch.cursor),
                        )
                record_run(conn, source, batch_id, started, records=landed, rejected=rejected)
            results[source] = landed
        except Exception as error:  # noqa: BLE001 - one failing source must not stop the others
            message = f"{type(error).__name__}: {error}"[:500]
            record_run(conn, source, batch_id, started, error=message)
            results[source] = f"failed: {message}"
    return results


def build(
    conn: psycopg.Connection, full_refresh: bool = False, replay: tuple[date, date] | None = None
) -> bool:
    """Run dbt (models, snapshots, then tests) and record every test result. True when all passed.

    Tests run after every model is built, not between them as `dbt build` does. With `dbt build`, a
    failed check skips everything downstream, and rebuilding a view drops the views that depend on it,
    so one bad record would take the marts offline. Here a failed check is recorded instead, and the
    agent's tools withhold the fields that depend on that model.
    """
    with one_run_at_a_time(conn):
        return _build(conn, full_refresh, replay)


def _build(conn: psycopg.Connection, full_refresh: bool, replay: tuple[date, date] | None) -> bool:
    # dbt connects with the same settings as `conn`, so it builds the database it was given.
    info = conn.info
    settings = {
        "host": info.host,
        "port": info.port,
        "user": info.user,
        "password": info.password,
        "dbname": info.dbname,
    }
    for key, value in settings.items():
        os.environ[f"NEXO_PG_{key.upper()}"] = str(value or "")
    common = ["--quiet", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    common += ["--target-path", str(DBT_DIR / "target"), "--log-path", str(DBT_DIR / "logs")]
    run = ["run", *common, *(["--full-refresh"] if full_refresh else [])]
    if replay:
        days = {"replay_from": replay[0].isoformat(), "replay_to": replay[1].isoformat()}
        run += ["--vars", json.dumps(days)]

    outcomes = [
        dbtRunner().invoke(args) for args in (run, ["snapshot", *common], ["test", *common])
    ]
    for outcome in outcomes:
        if outcome.result is None:  # dbt could not even start, for example a parse error
            raise RuntimeError(f"dbt did not run: {outcome.exception}")
    outcome = outcomes[-1]

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
        success = all(o.success for o in outcomes)
        conn.execute("insert into meta.build_runs (success) values (%s)", (success,))
        conn.execute("delete from meta.check_results")
        with conn.cursor() as cursor:
            cursor.executemany(
                "insert into meta.check_results (model, test, status, failures) values (%s, %s, %s, %s)",
                checks,
            )
    embed_documents(conn)
    return success


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
