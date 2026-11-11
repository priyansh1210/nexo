"""End-to-end pipeline tests against a real Postgres.

The tests run in order and share one database, a private copy of the built warehouse: each test
continues from the state the last one left.
"""

import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from data.pipelines import runner
from data.synthetic.generate import ACME
from services.mock_sources.main import create_app


@pytest.fixture(scope="module")
def pipeline(warehouse):
    copy = warehouse.copy("pipeline")
    data = warehouse.data
    helpdesk = TestClient(create_app(data))
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATABASE_URL", copy.url)
        with runner.connect() as conn:
            yield SimpleNamespace(
                conn=conn,
                data=data,
                today=warehouse.today,
                data_dir=copy.data_dir,
                helpdesk=helpdesk,
                sources=runner.connectors(copy.data_dir, helpdesk),
                acme_workspace=next(
                    a["workspace_id"] for a in data["accounts"] if a["account_id"] == ACME
                ),
                import_ticket=next(
                    t["ticket_id"] for t in data["tickets"] if "import" in t["subject"]
                ),
            )


def run(p) -> tuple[dict, bool]:
    return runner.sync(p.conn, p.sources), runner.build(p.conn)


def row(p, query: str, *params):
    return p.conn.execute(query, params).fetchone()


def append_events(p, *events: dict) -> None:
    with open(p.data_dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as log:
        log.writelines(json.dumps(event) + "\n" for event in events)


def event(p, event_id: str, day) -> dict:
    return {
        "event_id": event_id,
        "workspace_id": p.acme_workspace,
        "user_id": "u_test",
        "name": "feature_used",
        "properties": {"feature": "reports"},
        "occurred_at": f"{day.isoformat()}T10:00:00Z",
    }


def marts_fingerprint(p) -> dict[str, str]:
    """A checksum of every table and view in the marts schema."""
    names = p.conn.execute(
        "select table_name from information_schema.tables where table_schema = 'marts'"
    ).fetchall()
    checksum = sql.SQL(
        "select md5(coalesce(string_agg(t::text, '|' order by t::text), '')) from {} t"
    )
    return {
        name: p.conn.execute(checksum.format(sql.Identifier("marts", name))).fetchone()[0]
        for (name,) in names
    }


def test_first_run_loads_every_source_and_every_check_passes(pipeline, warehouse):
    data = pipeline.data
    assert warehouse.first_build
    assert warehouse.first_sync == {
        "crm": len(data["accounts"]) + len(data["contacts"]),
        "product_events": len(data["events"]),
        "support_tickets": len(data["tickets"]),
        "billing": len(data["invoices"]),
        "documents": len(data["documents"]),
    }
    staged = row(pipeline, "select count(*) from staging.stg_events")[0]
    assert staged == len({e["event_id"] for e in data["events"]}) < len(data["events"])

    checks = dict(
        pipeline.conn.execute(
            "select status, count(*) from meta.check_results group by 1"
        ).fetchall()
    )
    assert set(checks) == {"pass"} and checks["pass"] > 25
    fresh = pipeline.conn.execute("select distinct status from meta.source_freshness").fetchall()
    assert fresh == [("fresh",)]


def test_marts_tell_the_seeded_story(pipeline):
    at_risk = pipeline.conn.execute(
        "select account_id from marts.renewals_upcoming "
        "where renews_next_month and is_at_risk order by usage_change"
    ).fetchall()
    assert at_risk == [(ACME,), ("acct_0001",), ("acct_0002",)]
    assert row(
        pipeline, "select count(*) from marts.renewals_upcoming where renews_next_month"
    ) == (6,)

    trend = "select events_prior_30d, events_last_30d, usage_change from marts.fct_usage_trend"
    assert row(pipeline, trend + " where account_id = %s", ACME) == (1500, 900, Decimal("-0.4000"))
    health = (
        "select risk_usage_drop, risk_stale_ticket, risk_overdue_invoice "
        "from marts.account_health where account_id = %s"
    )
    assert row(pipeline, health, ACME) == (True, True, False)
    assert row(pipeline, health, "acct_0002") == (True, False, True)
    onboarding = "select steps_completed, data_import_at, is_complete from marts.fct_onboarding"
    assert row(pipeline, onboarding + " where account_id = %s", ACME) == (3, None, False)

    # The account with no workspace in the CRM is reported as unknown, not as zero usage.
    unlinked = "select usage_status, usage_change from marts.account_health where account_id = %s"
    assert row(pipeline, unlinked, "acct_0006") == ("no_linked_workspace", None)
    queue = pipeline.conn.execute(
        "select problem, count(*) from marts.identity_unmatched group by 1 order by 1"
    ).fetchall()
    assert queue == [("account_without_workspace", 1), ("workspace_without_account", 1)]


def test_running_again_changes_nothing(pipeline):
    # A view's identity in Postgres. If a rebuild dropped it, even briefly, this would change.
    view_ids = "select relname, oid from pg_class where relname in ('account_health', 'renewals_upcoming', 'fct_tickets') order by 1"
    views_before = pipeline.conn.execute(view_ids).fetchall()
    before = marts_fingerprint(pipeline), row(pipeline, "select count(*) from raw.product_events")
    synced, built = run(pipeline)
    assert built and set(synced.values()) == {0}
    assert (
        marts_fingerprint(pipeline),
        row(pipeline, "select count(*) from raw.product_events"),
    ) == before
    versions = row(pipeline, "select count(*) from snapshots.accounts_history")[0]
    assert versions == len(pipeline.data["accounts"])  # no account changed, so no new history rows
    # Views were replaced in place, never dropped, so the API never sees them missing.
    assert pipeline.conn.execute(view_ids).fetchall() == views_before


def test_a_table_whose_column_type_changed_is_rebuilt_not_refilled(pipeline):
    # Refilling would convert the new values into the old column type, quietly.
    column_type = (
        "select data_type from information_schema.columns"
        " where table_name = 'fct_usage_by_feature' and column_name = 'events_last_30d'"
    )
    built_type = row(pipeline, column_type)
    pipeline.conn.execute(
        "alter table marts.fct_usage_by_feature alter column events_last_30d type text"
    )
    assert run(pipeline)[1]
    assert row(pipeline, column_type) == built_type


def test_a_duplicate_changes_nothing_and_a_late_event_lands_on_its_own_day(pipeline):
    late_day = pipeline.today - timedelta(days=45)  # inside the prior 30-day window
    on_late_day = "select coalesce(sum(events), 0) from marts.fct_usage_daily where account_id = %s and day = %s"
    staged_before = row(pipeline, "select count(*) from staging.stg_events")[0]
    day_before = row(pipeline, on_late_day, ACME, late_day)[0]

    append_events(pipeline, pipeline.data["events"][0], event(pipeline, "evt_late", late_day))
    synced, built = run(pipeline)

    assert built and synced["product_events"] == 2
    assert row(pipeline, "select count(*) from staging.stg_events")[0] == staged_before + 1
    assert row(pipeline, on_late_day, ACME, late_day)[0] == day_before + 1
    trend = (
        "select events_prior_30d, events_last_30d from marts.fct_usage_trend where account_id = %s"
    )
    assert row(pipeline, trend, ACME) == (1501, 900)


def test_a_ticket_solved_at_the_source_reaches_the_warehouse(pipeline):
    ticket = pipeline.import_ticket
    pipeline.helpdesk.patch(f"/helpdesk/tickets/{ticket}", json={"status": "solved"})
    synced, built = run(pipeline)
    assert built and synced["support_tickets"] == 1

    assert row(pipeline, "select status from marts.fct_tickets where ticket_id = %s", ticket) == (
        "solved",
    )
    health = "select risk_stale_ticket, is_at_risk from marts.account_health where account_id = %s"
    assert row(pipeline, health, ACME) == (False, True)  # still at risk: usage is still down
    versions = "select count(*) from raw.support_tickets where payload->>'ticket_id' = %s"
    assert row(pipeline, versions, ticket) == (2,)  # raw keeps both versions


def test_replay_rebuilds_the_same_marts(pipeline):
    before = marts_fingerprint(pipeline)
    assert runner.build(pipeline.conn, full_refresh=True)
    assert marts_fingerprint(pipeline) == before
    days = (pipeline.today - timedelta(days=50), pipeline.today - timedelta(days=40))
    assert runner.build(pipeline.conn, replay=days)
    assert marts_fingerprint(pipeline) == before


def test_a_stalled_source_reads_stale_and_is_skipped_until_resumed(pipeline):
    freshness = "select status, now() - last_updated from meta.source_freshness where source = %s"
    assert row(pipeline, freshness, "product_events")[0] == "fresh"

    runner.stall(pipeline.conn, "product_events", hours=48)
    status, age = row(pipeline, freshness, "product_events")
    assert status == "stale" and timedelta(hours=47.9) < age < timedelta(hours=48.1)
    assert row(pipeline, freshness, "support_tickets")[0] == "fresh"  # other sources are unaffected

    append_events(pipeline, event(pipeline, "evt_during_stall", pipeline.today - timedelta(days=2)))
    assert runner.sync(pipeline.conn, pipeline.sources)["product_events"] == "stalled"

    runner.resume(pipeline.conn, "product_events")
    assert runner.sync(pipeline.conn, pipeline.sources)["product_events"] == 1
    assert row(pipeline, freshness, "product_events")[0] == "fresh"
    with pytest.raises(ValueError, match="unknown source"):
        runner.stall(pipeline.conn, "nope", hours=1)


def test_a_failing_source_is_recorded_and_the_others_still_sync(pipeline):
    class DownHelpdesk:
        source, streams = "support_tickets", ("support_tickets",)

        def read(self, stream, cursor):
            raise ConnectionError("helpdesk is down")

    sources = [DownHelpdesk() if s.source == "support_tickets" else s for s in pipeline.sources]
    synced = runner.sync(pipeline.conn, sources)
    assert synced["support_tickets"] == "failed: ConnectionError: helpdesk is down"
    assert synced["crm"] == 0 and runner.failed_sources(synced) == ["support_tickets"]
    last = "select status, error from meta.sync_runs where source = %s order by id desc limit 1"
    assert row(pipeline, last, "support_tickets") == ("failed", "ConnectionError: helpdesk is down")


def test_a_failed_check_is_recorded_against_its_model(pipeline):
    bad_ticket = {
        "ticket_id": "tkt_bad",
        "org_id": "org_x",
        "severity": "catastrophic",  # not an accepted value
        "status": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    pipeline.conn.execute(
        "insert into raw.support_tickets (payload, _source, _batch_id) values (%s, 'test', gen_random_uuid())",
        (Jsonb(bad_ticket),),
    )
    assert not runner.build(pipeline.conn)
    failed = pipeline.conn.execute(
        "select model from meta.check_results where status = 'fail'"
    ).fetchall()
    assert failed == [("stg_tickets",)]
    # The failed check is recorded, and nothing downstream was taken offline by it.
    assert row(
        pipeline, "select count(*) from marts.renewals_upcoming where renews_next_month"
    ) == (6,)
    assert row(pipeline, "select count(*) from marts.fct_tickets where ticket_id = 'tkt_bad'") == (
        1,
    )


def test_the_schema_can_be_created_by_several_services_at_once(pipeline, warehouse):
    # The API and the pipeline both create it at startup; before the lock, one of them crashed.
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    from data.landing import ensure_schema

    copy = warehouse.copy("schema_race")
    with psycopg.connect(copy.url, autocommit=True) as conn:
        conn.execute("drop schema meta cascade")

    def create(_):
        with psycopg.connect(copy.url, autocommit=True) as conn:
            ensure_schema(conn)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(create, range(6)))


def test_a_second_run_waits_for_the_one_in_progress(pipeline):
    # Two runs at once would count usage twice; `make sync` during the hourly run must wait.
    import threading

    finished = threading.Event()

    def second_run():
        with runner.connect() as conn:
            runner.sync(conn, pipeline.sources)
        finished.set()

    with runner.connect() as first_run:
        first_run.execute("select pg_advisory_lock(%s)", (runner.RUN_LOCK,))
        waiting = threading.Thread(target=second_run)
        waiting.start()
        assert not finished.wait(3)  # still waiting while the first run holds the lock
        first_run.execute("select pg_advisory_unlock(%s)", (runner.RUN_LOCK,))
    waiting.join(120)
    assert finished.is_set()


def test_a_bad_event_is_set_aside_and_the_rest_still_lands(pipeline):
    before = row(pipeline, "select count(*) from raw.product_events")[0]
    good = {
        "event_id": "evt_after_bad_line",
        "workspace_id": pipeline.acme_workspace,
        "user_id": "u_1",
        "name": "login",
        "occurred_at": "2026-11-01T09:00:00Z",
    }
    with open(pipeline.data_dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as log:
        log.write("{broken\n")
    append_events(pipeline, good)

    synced, _ = run(pipeline)
    assert synced["product_events"] == 1
    assert row(pipeline, "select count(*) from raw.product_events")[0] == before + 1
    assert row(pipeline, "select record from meta.dead_letters") == ("{broken",)
    assert row(
        pipeline,
        "select rejected_last_day from meta.source_freshness where source = 'product_events'",
    ) == (1,)


def test_only_new_or_changed_documents_are_embedded(pipeline):
    from data.embeddings import embed_documents

    assert embed_documents(pipeline.conn) == 0  # the last build embedded every document already
    pipeline.conn.execute(
        "update vec.document_chunks set body = 'out of date' "
        "where doc_id = (select min(doc_id) from vec.document_chunks)"
    )
    assert embed_documents(pipeline.conn) == 1
