"""Contract tests for API keys and the push side of ingestion, through to the warehouse.

The tests run in order: the earlier ones push data, the last one runs the pipeline once and checks
that everything pushed arrived.
"""

import csv
import io
from datetime import UTC, datetime, timedelta

import psycopg

from data.pipelines import runner
from data.synthetic.generate import ACME

CSV = {"Content-Type": "text/csv"}


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def new_key(api, name: str) -> dict:
    created = api.admin.post("/api-keys", json={"name": name})
    assert created.status_code == 201
    return created.json()


def acme(api) -> dict:
    return next(a for a in api.data["accounts"] if a["account_id"] == ACME)


def event(api, **changes) -> dict:
    day = api.today - timedelta(days=45)  # inside the prior 30-day window
    base = {
        "workspace_id": acme(api)["workspace_id"],
        "user_id": "u_pushed",
        "name": "feature_used",
        "properties": {"feature": "reports"},
        "occurred_at": f"{day.isoformat()}T10:00:00Z",
    }
    return base | changes


def as_csv(rows: list[dict]) -> bytes:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode()


def count(api, query: str, *params) -> int:
    with psycopg.connect(api.url) as db:
        return db.execute(query, params).fetchone()[0]


def test_an_api_key_is_shown_once_kept_as_a_hash_and_dies_when_revoked(api):
    key = new_key(api, "backend")
    assert key["key"].startswith("nexo_")
    listed = api.admin.get("/api-keys").json()
    assert [k["name"] for k in listed] == ["backend"] and "key" not in listed[0]
    assert count(api, "select count(*) from app.api_keys where key_hash = %s", key["key"]) == 0

    batch = {"events": [event(api, workspace_id="ws_unknown_backend")]}
    assert (
        api.anonymous.post("/ingest/events", json=batch, headers=bearer(key["key"])).status_code
        == 202
    )
    assert (
        api.anonymous.post("/ingest/events", json=batch, headers=bearer("nexo_wrong")).status_code
        == 401
    )

    assert api.admin.delete(f"/api-keys/{key['key_id']}").status_code == 204
    assert (
        api.anonymous.post("/ingest/events", json=batch, headers=bearer(key["key"])).status_code
        == 401
    )
    assert api.admin.delete(f"/api-keys/{key['key_id']}").status_code == 404
    assert api.csm.post("/api-keys", json={"name": "not allowed"}).status_code == 403

    latest = api.admin.get("/audit", params={"limit": 3}).json()
    assert [e["action"] for e in latest] == [
        "api_key.revoked",
        "ingest.product_events",
        "api_key.created",
    ]


def test_malformed_events_are_refused_and_nothing_lands(api):
    before = count(api, "select count(*) from raw.product_events")
    good = event(api)
    soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    bad_events = {
        "no time zone": good | {"occurred_at": "2026-11-01T10:00:00"},
        "in the future": good | {"occurred_at": soon},
        "no workspace": {k: v for k, v in good.items() if k != "workspace_id"},
        "nested properties": good | {"properties": {"a": {"b": 1}}},
    }
    for reason, bad in bad_events.items():
        refused = api.admin.post("/ingest/events", json={"events": [good, bad]})
        assert refused.status_code == 422, reason
    assert api.admin.post("/ingest/events", json={"events": []}).status_code == 422
    assert api.admin.post("/ingest/events", json={"events": [good] * 5001}).status_code == 422
    assert count(api, "select count(*) from raw.product_events") == before


def test_pushed_events_land_with_who_pushed_them(api):
    key = new_key(api, "product backend")["key"]
    with_id, without_id = event(api, event_id="evt_pushed"), event(api, user_id="u_pushed_2")
    no_feature = event(api, event_id="evt_no_feature", properties={})
    batch = {
        "events": [
            with_id,
            with_id,
            without_id,
            without_id,
            event(api, name="page_viewed"),
            no_feature,
        ]
    }
    landed = api.anonymous.post("/ingest/events", json=batch, headers=bearer(key))
    assert landed.status_code == 202 and landed.json()["landed"] == 6

    batch_id = landed.json()["batch_id"]
    with psycopg.connect(api.url) as db:
        origin = db.execute(
            "select distinct _source from raw.product_events where _batch_id = %s", (batch_id,)
        )
        assert origin.fetchall() == [("push by api key product backend",)]
        run = db.execute(
            "select source, status, records from meta.sync_runs where batch_id = %s", (batch_id,)
        )
        assert run.fetchone() == ("product_events", "success", 6)
        audited = db.execute(
            "select actor_id, action, target_id, detail from audit.events "
            "where target_type = 'batch' and target_id = %s",
            (batch_id,),
        ).fetchone()
        assert audited[:3] == (None, "ingest.product_events", batch_id)
        assert audited[3]["pushed_by"] == "api key product backend" and audited[3]["records"] == 6


def test_pushed_tickets_are_validated_before_they_land(api):
    opened = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    ticket = {
        "ticket_id": "tkt_pushed",
        "org_id": acme(api)["support_org_id"],
        "subject": "Export fails for large reports",
        "severity": "urgent",
        "status": "open",
        "created_at": opened,
        "updated_at": opened,
    }
    bad = {"tickets": [ticket | {"severity": "catastrophic"}]}
    assert api.admin.post("/ingest/tickets", json=bad).status_code == 422
    assert (
        count(
            api,
            "select count(*) from raw.support_tickets where payload->>'ticket_id' = 'tkt_pushed'",
        )
        == 0
    )
    assert api.admin.post("/ingest/tickets", json={"tickets": [ticket]}).json()["landed"] == 1


def test_a_crm_import_is_checked_row_by_row_and_refused_whole(api):
    rows = [dict(a) for a in api.data["accounts"]]
    bad = as_csv([rows[0] | {"seats": "many"}, rows[1] | {"renewal_date": "next year"}])
    refused = api.admin.post("/import/crm/accounts", content=bad, headers=CSV)
    assert refused.status_code == 422
    problems = refused.json()["detail"]["problems"]
    assert (
        len(problems) == 2 and problems[0].startswith("line 2, seats:") and "line 3" in problems[1]
    )
    assert (
        api.admin.post("/import/crm/accounts", content=as_csv(rows)[:120], headers=CSV).status_code
        == 422
    )
    assert (
        api.admin.post("/import/crm/invoices", content=as_csv(rows), headers=CSV).status_code == 422
    )

    # Acme changes owner. The file carries the byte-order mark Excel adds, which must be accepted.
    changed = [r | {"owner_name": "Daniel Reyes"} if r["account_id"] == ACME else r for r in rows]
    imported = api.admin.post(
        "/import/crm/accounts", content=b"\xef\xbb\xbf" + as_csv(changed), headers=CSV
    )
    assert imported.status_code == 202 and imported.json()["landed"] == len(rows)
    latest = api.admin.get("/audit", params={"action": "ingest.crm_accounts"}).json()
    assert latest[0]["actor_email"] == "admin@nexo.example"
    assert latest[0]["detail"]["records"] == len(rows)


def test_one_pipeline_run_carries_everything_pushed_into_the_warehouse(api):
    with runner.connect() as conn:
        assert runner.build(conn)  # the unknown event name must not fail the build

    profile = api.viewer.get(f"/accounts/{ACME}").json()
    assert profile["usage"]["events_prior_30d"] == 1503  # three distinct pushed events, each once
    # The feature event that named no feature is counted under its own name, not as a login.
    features = {
        f["feature"]: f for f in api.viewer.get(f"/accounts/{ACME}/usage").json()["features"]
    }
    assert features["feature_used"]["events_prior_30d"] == 1
    assert "tkt_pushed" in [t["ticket_id"] for t in profile["tickets"]]
    assert profile["account"]["stale_high_tickets"] == 2
    assert profile["account"]["owner_name"] == "Daniel Reyes"
    assert profile["checks"]["failed"] == 0

    with psycopg.connect(api.url) as db:
        history = db.execute(
            "select owner_name, dbt_valid_to is null from snapshots.accounts_history "
            "where account_id = %s order by dbt_valid_from",
            (ACME,),
        ).fetchall()
        assert history == [("Maya Okafor", False), ("Daniel Reyes", True)]  # the old owner is kept
        warned = db.execute("select model from meta.check_results where status = 'warn'").fetchall()
        assert warned == [("stg_events",)]
        queue = db.execute(
            "select count(*) from marts.identity_unmatched where key = 'ws_unknown_backend'"
        ).fetchone()
        assert queue == (1,)


def test_a_body_over_the_limit_is_refused_before_it_is_read_whole(api):
    from apps.api.main import MAX_BODY_BYTES

    big = b"x" * (MAX_BODY_BYTES + 1)
    headers = {"Content-Type": "text/csv"}
    declared = api.admin.post("/import/crm/accounts", content=big, headers=headers)
    assert declared.status_code == 413

    def chunks():  # sent in pieces with no declared length, so the limit must count as it reads
        for start in range(0, len(big), 1024 * 1024):
            yield big[start : start + 1024 * 1024]

    streamed = api.admin.post("/import/crm/accounts", content=chunks(), headers=headers)
    assert streamed.status_code == 413
