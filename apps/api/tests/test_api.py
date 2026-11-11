"""Contract tests for the API, against a private copy of the built warehouse."""

import re
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient

from apps.api.auth import DEMO_PASSWORD
from apps.api.main import app
from data.synthetic.generate import ACME

MAYA = "maya.okafor@nexo.example"  # a csm, and Acme's owner
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
OPEN_WRITES = {("POST", "/auth/login"), ("POST", "/auth/logout")}


def signed_in(email: str) -> TestClient:
    client = TestClient(app)
    assert (
        client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD}).status_code
        == 200
    )
    return client


@pytest.fixture(scope="module")
def api(warehouse):
    copy = warehouse.copy("api")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATABASE_URL", copy.url)
        env.setenv("NEXO_DEMO_USERS", "1")
        with TestClient(app) as anonymous:  # entering runs startup: schema and demo users
            yield SimpleNamespace(
                anonymous=anonymous,
                viewer=signed_in("viewer@nexo.example"),
                csm=signed_in(MAYA),
                url=copy.url,
                data=warehouse.data,
            )


def test_sign_in_sign_out_and_who_am_i(api):
    wrong = {"email": MAYA, "password": "not-the-password"}
    unknown = {"email": "nobody@nexo.example", "password": DEMO_PASSWORD}
    assert api.anonymous.post("/auth/login", json=wrong).status_code == 401
    assert api.anonymous.post("/auth/login", json=unknown).json() == {
        "detail": "Wrong email or password"
    }
    assert api.anonymous.get("/auth/me").status_code == 401

    client = signed_in(MAYA.upper())  # the email is not case sensitive
    me = client.get("/auth/me").json()
    assert me == {"user_id": me["user_id"], "email": MAYA, "name": "Maya Okafor", "role": "csm"}

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_an_expired_session_is_refused(api):
    client = signed_in("viewer@nexo.example")
    token = client.cookies["nexo_session"]
    with psycopg.connect(api.url) as db:
        assert db.execute(
            "select count(*) from app.sessions where token_hash = %s", (token,)
        ).fetchone() == (0,)
        db.execute("update app.sessions set expires_at = now() - interval '1 second'")
    assert client.get("/auth/me").status_code == 401
    api.viewer, api.csm = (
        signed_in("viewer@nexo.example"),
        signed_in(MAYA),
    )  # the update expired theirs too


def test_every_write_route_refuses_the_anonymous_and_the_viewer(api):
    # The routes are read from the published API schema, so a route added later is checked too.
    checked = []
    for path, operations in app.openapi()["paths"].items():
        for method in {m.upper() for m in operations} & WRITE_METHODS:
            if (method, path) in OPEN_WRITES:
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            assert api.anonymous.request(method, url, json={}).status_code == 401, (method, path)
            assert api.viewer.request(method, url, json={}).status_code == 403, (method, path)
            checked.append((method, path))
    assert len(checked) >= 3
    assert api.anonymous.get("/accounts").status_code == 401  # reads need a sign-in too


def test_account_list_carries_health_freshness_and_checks(api):
    body = api.viewer.get("/accounts").json()
    assert len(body["accounts"]) == len(api.data["accounts"])

    acme = next(a for a in body["accounts"] if a["account_id"] == ACME)
    assert acme["usage_change"] == -0.4 and acme["usage_status"] == "ok"
    assert (acme["risk_usage_drop"], acme["risk_stale_ticket"], acme["risk_overdue_invoice"]) == (
        True,
        True,
        False,
    )
    assert acme["is_at_risk"] and acme["open_tickets"] >= 1 and acme["owner_email"] == MAYA

    unlinked = next(a for a in body["accounts"] if a["account_id"] == "acct_0006")
    assert unlinked["usage_status"] == "no_linked_workspace" and unlinked["usage_change"] is None

    assert {f["source"]: f["status"] for f in body["freshness"]} == {
        "billing": "fresh",
        "crm": "fresh",
        "documents": "fresh",
        "product_events": "fresh",
        "support_tickets": "fresh",
    }
    assert body["freshness"][0]["expected_every_seconds"] == 24 * 3600
    assert body["checks"]["failed"] == 0 and body["checks"]["passed"] > 25
    assert api.viewer.get("/freshness").json() == body["freshness"]


def test_account_profile(api):
    profile = api.viewer.get(f"/accounts/{ACME}").json()
    assert profile["account"]["name"] == "Acme Corp"
    assert (profile["usage"]["events_prior_30d"], profile["usage"]["events_last_30d"]) == (
        1500,
        900,
    )
    assert (
        profile["onboarding"]["steps_completed"] == 3
        and profile["onboarding"]["data_import_at"] is None
    )
    assert profile["tickets"][0]["is_open"] and "import" in profile["tickets"][0]["subject"]
    assert {c["role"]: c["name"] for c in profile["contacts"]}["admin"] == "Jordan Blake"
    assert len(profile["freshness"]) == 5 and profile["checks"]["failed"] == 0

    assert api.viewer.get("/accounts/acct_0006").json()["usage"] is None
    assert api.viewer.get("/accounts/nope").status_code == 404


def test_notes_are_written_by_a_csm_and_audited(api):
    notes = f"/accounts/{ACME}/notes"
    created = api.csm.post(notes, json={"body": "  Called Jordan about the import.  "})
    assert created.status_code == 201
    note = created.json()
    assert (
        note["body"] == "Called Jordan about the import." and note["author_name"] == "Maya Okafor"
    )
    assert api.viewer.get(notes).json() == [note]

    assert api.csm.post(notes, json={"body": "   "}).status_code == 422
    assert api.csm.post("/accounts/nope/notes", json={"body": "x"}).status_code == 404

    event = api.csm.get("/audit", params={"action": "note.created"}).json()[0]
    assert (event["actor_email"], event["account_id"], event["target_id"]) == (
        MAYA,
        ACME,
        str(note["note_id"]),
    )


def test_tasks_are_created_changed_and_audited_with_before_and_after(api):
    daniel = "daniel.reyes@nexo.example"
    created = api.csm.post(
        f"/accounts/{ACME}/tasks", json={"title": "Follow up on the import ticket"}
    )
    assert created.status_code == 201
    task = created.json()
    assert (task["status"], task["assignee_email"], task["created_by_name"]) == (
        "open",
        None,
        "Maya Okafor",
    )

    changed = api.csm.patch(
        f"/tasks/{task['task_id']}", json={"status": "done", "assignee_email": daniel}
    )
    assert (changed.json()["status"], changed.json()["assignee_name"]) == ("done", "Daniel Reyes")
    assert api.viewer.get(f"/accounts/{ACME}/tasks").json() == [changed.json()]
    assert api.viewer.get("/tasks").json() == [changed.json()]
    assert api.viewer.get("/tasks", params={"mine": True}).json() == []

    event = api.csm.get("/audit", params={"action": "task.updated"}).json()[0]
    assert event["detail"] == {
        "before": {"status": "open", "assignee_email": None},
        "after": {"status": "done", "assignee_email": daniel},
    }

    task_url = f"/tasks/{task['task_id']}"
    assert api.csm.patch(task_url, json={}).status_code == 422
    assert (
        api.csm.patch(task_url, json={"assignee_email": "nobody@nexo.example"}).status_code == 422
    )
    assert api.csm.patch("/tasks/999999", json={"status": "done"}).status_code == 404
    assert api.csm.post(f"/accounts/{ACME}/tasks", json={"title": ""}).status_code == 422


def test_audit_log_is_filtered_restricted_and_append_only(api):
    assert api.viewer.get("/audit").status_code == 403
    for_acme = api.csm.get("/audit", params={"account_id": ACME}).json()
    assert {e["action"] for e in for_acme} == {"note.created", "task.created", "task.updated"}
    assert [e["event_id"] for e in for_acme] == sorted(
        (e["event_id"] for e in for_acme), reverse=True
    )
    assert len(api.csm.get("/audit", params={"limit": 2}).json()) == 2

    with psycopg.connect(api.url) as db:
        for change in (
            "update audit.events set action = 'x'",
            "delete from audit.events",
            "truncate audit.events",
        ):
            with (
                pytest.raises(psycopg.errors.RaiseException, match="append-only"),
                db.transaction(),
            ):
                db.execute(change)


def test_a_failed_write_leaves_no_audit_row(api):
    before = len(api.csm.get("/audit").json())
    assert api.csm.patch("/tasks/999999", json={"status": "done"}).status_code == 404
    assert len(api.csm.get("/audit").json()) == before


def test_a_write_is_saved_before_its_response_is_sent(api):
    # A client may act on a reply at once, for example sign in and then fetch. So the write behind
    # a reply must already be committed when the reply starts to go out. This looks at the database
    # from a second connection at exactly that moment.
    visible = []

    async def app_with_probe(scope, receive, send):
        async def probing_send(message):
            if message["type"] == "http.response.start":
                with psycopg.connect(api.url) as db:
                    found = db.execute("select count(*) from app.notes where body = 'commit probe'")
                    visible.append(found.fetchone()[0])
            await send(message)

        await app(scope, receive, probing_send)

    client = TestClient(app_with_probe, cookies=api.csm.cookies)
    assert (
        client.post("/accounts/acct_0001/notes", json={"body": "commit probe"}).status_code == 201
    )
    assert visible == [1]


def test_warehouse_routes_say_so_when_the_warehouse_is_not_built(api):
    with psycopg.connect(api.url, autocommit=True) as db:
        db.execute("alter schema marts rename to marts_hidden")
        try:
            response = api.viewer.get("/accounts")
            assert response.status_code == 503 and "not built yet" in response.json()["detail"]
        finally:
            db.execute("alter schema marts_hidden rename to marts")
    assert api.viewer.get("/accounts").status_code == 200
