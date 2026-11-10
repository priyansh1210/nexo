"""End-to-end pipeline tests against a real Postgres in a throwaway container.

The tests run in order and share one database: each continues from the state the last one left.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb
from testcontainers.community.postgres import PostgresContainer

from data.pipelines import runner
from data.synthetic.generate import ACME, generate, write
from services.mock_sources.main import create_app

TODAY = datetime.now(UTC).date()  # the database runs in UTC, so "today" must be the UTC date too
DATA = generate(seed=7, as_of=TODAY)
ACME_WORKSPACE = next(a["workspace_id"] for a in DATA["accounts"] if a["account_id"] == ACME)
IMPORT_TICKET = next(t["ticket_id"] for t in DATA["tickets"] if "import" in t["subject"])


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("sources")
    write(DATA, data_dir)
    helpdesk = TestClient(create_app(DATA))
    with (
        PostgresContainer("pgvector/pgvector:pg16", driver=None) as postgres,
        pytest.MonkeyPatch.context() as env,
    ):
        env.setenv("DATABASE_URL", postgres.get_connection_url())
        with runner.connect() as conn:
            yield SimpleNamespace(
                conn=conn,
                data_dir=data_dir,
                helpdesk=helpdesk,
                sources=runner.connectors(data_dir, helpdesk),
            )


def run(p) -> tuple[dict, bool]:
    return runner.sync(p.conn, p.sources), runner.build(p.conn)


def row(p, query: str, *params):
    return p.conn.execute(query, params).fetchone()


def append_events(p, *events: dict) -> None:
    with open(p.data_dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as log:
        log.writelines(json.dumps(event) + "\n" for event in events)


def event(event_id: str, day) -> dict:
    return {
        "event_id": event_id,
        "workspace_id": ACME_WORKSPACE,
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


def test_first_run_loads_every_source_and_every_check_passes(pipeline):
    synced, built = run(pipeline)
    assert built
    assert synced == {
        "crm": len(DATA["accounts"]) + len(DATA["contacts"]),
        "product_events": len(DATA["events"]),
        "support_tickets": len(DATA["tickets"]),
        "billing": len(DATA["invoices"]),
        "documents": len(DATA["documents"]),
    }
    staged = row(pipeline, "select count(*) from staging.stg_events")[0]
    assert staged == len({e["event_id"] for e in DATA["events"]}) < len(DATA["events"])

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
    before = marts_fingerprint(pipeline), row(pipeline, "select count(*) from raw.product_events")
    synced, built = run(pipeline)
    assert built and set(synced.values()) == {0}
    assert (
        marts_fingerprint(pipeline),
        row(pipeline, "select count(*) from raw.product_events"),
    ) == before
    versions = row(pipeline, "select count(*) from snapshots.accounts_history")[0]
    assert versions == len(DATA["accounts"])  # no account changed, so no new history rows


def test_a_duplicate_changes_nothing_and_a_late_event_lands_on_its_own_day(pipeline):
    late_day = TODAY - timedelta(days=45)  # inside the prior 30-day window
    on_late_day = "select coalesce(sum(events), 0) from marts.fct_usage_daily where account_id = %s and day = %s"
    staged_before = row(pipeline, "select count(*) from staging.stg_events")[0]
    day_before = row(pipeline, on_late_day, ACME, late_day)[0]

    append_events(pipeline, DATA["events"][0], event("evt_late", late_day))
    synced, built = run(pipeline)

    assert built and synced["product_events"] == 2
    assert row(pipeline, "select count(*) from staging.stg_events")[0] == staged_before + 1
    assert row(pipeline, on_late_day, ACME, late_day)[0] == day_before + 1
    trend = (
        "select events_prior_30d, events_last_30d from marts.fct_usage_trend where account_id = %s"
    )
    assert row(pipeline, trend, ACME) == (1501, 900)


def test_a_ticket_solved_at_the_source_reaches_the_warehouse(pipeline):
    pipeline.helpdesk.patch(f"/helpdesk/tickets/{IMPORT_TICKET}", json={"status": "solved"})
    synced, built = run(pipeline)
    assert built and synced["support_tickets"] == 1

    assert row(
        pipeline, "select status from marts.fct_tickets where ticket_id = %s", IMPORT_TICKET
    ) == ("solved",)
    health = "select risk_stale_ticket, is_at_risk from marts.account_health where account_id = %s"
    assert row(pipeline, health, ACME) == (False, True)  # still at risk: usage is still down
    versions = "select count(*) from raw.support_tickets where payload->>'ticket_id' = %s"
    assert row(pipeline, versions, IMPORT_TICKET) == (2,)  # raw keeps both versions


def test_replay_rebuilds_the_same_marts(pipeline):
    before = marts_fingerprint(pipeline)
    assert runner.build(pipeline.conn, full_refresh=True)
    assert marts_fingerprint(pipeline) == before
    days = (TODAY - timedelta(days=50), TODAY - timedelta(days=40))
    assert runner.build(pipeline.conn, replay=days)
    assert marts_fingerprint(pipeline) == before


def test_a_stalled_source_reads_stale_and_is_skipped_until_resumed(pipeline):
    freshness = "select status, now() - last_updated from meta.source_freshness where source = %s"
    assert row(pipeline, freshness, "product_events")[0] == "fresh"

    runner.stall(pipeline.conn, "product_events", hours=48)
    status, age = row(pipeline, freshness, "product_events")
    assert status == "stale" and timedelta(hours=47.9) < age < timedelta(hours=48.1)
    assert row(pipeline, freshness, "support_tickets")[0] == "fresh"  # other sources are unaffected

    append_events(pipeline, event("evt_during_stall", TODAY - timedelta(days=2)))
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
