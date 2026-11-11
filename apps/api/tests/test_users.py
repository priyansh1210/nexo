"""Contract tests for real users, the sign-in rate limit, and usage by feature."""

import psycopg
import pytest

from apps.api import users
from apps.api.auth import DEMO_PASSWORD, MAX_FAILED_LOGINS
from data.synthetic.generate import ACME

PASSWORD = "correct horse battery"


def login(api, email: str, password: str):
    return api.anonymous.post("/auth/login", json={"email": email, "password": password})


def test_an_admin_creates_a_user_who_can_then_sign_in(api):
    new = {
        "email": " Priya@Company.com ",
        "name": "Priya Shah",
        "role": "csm",
        "password": PASSWORD,
    }
    created = api.admin.post("/users", json=new)
    assert created.status_code == 201
    assert created.json()["email"] == "priya@company.com" and created.json()["role"] == "csm"
    assert login(api, "priya@company.com", PASSWORD).status_code == 200

    assert api.admin.post("/users", json=new | {"email": "PRIYA@company.com"}).status_code == 409
    assert (
        api.admin.post("/users", json=new | {"email": "x@y.z", "password": "short"}).status_code
        == 422
    )
    assert api.admin.post("/users", json=new | {"email": "not-an-email"}).status_code == 422
    assert (
        api.admin.post("/users", json=new | {"email": "a@b.co", "role": "owner"}).status_code == 422
    )
    assert api.csm.post("/users", json=new | {"email": "c@d.co"}).status_code == 403
    assert api.csm.get("/users").status_code == 403
    assert "priya@company.com" in [u["email"] for u in api.admin.get("/users").json()]

    audited = api.admin.get("/audit", params={"action": "user.created"}).json()[0]
    assert audited["detail"] == {"email": "priya@company.com", "role": "csm"}
    assert PASSWORD not in str(audited)


def test_the_first_admin_is_created_from_the_command_line(api, monkeypatch, capsys):
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(users.getpass, "getpass", lambda prompt: next(answers))
    args = ["create", "--email", "Founder@Company.com", "--name", "Founder"]
    assert users.main(args) == 0
    assert capsys.readouterr().out.strip() == "Created admin founder@company.com"
    me = api.sign_in_with("founder@company.com", PASSWORD).get("/auth/me").json()
    assert me["role"] == "admin"

    monkeypatch.setattr(users.getpass, "getpass", lambda prompt: PASSWORD)
    with pytest.raises(SystemExit):  # the email is taken
        users.main(args)
    mismatched = iter([PASSWORD, PASSWORD + "!"])
    monkeypatch.setattr(users.getpass, "getpass", lambda prompt: next(mismatched))
    with pytest.raises(SystemExit):
        users.main(["create", "--email", "second@company.com", "--name", "Second"])

    with psycopg.connect(api.url) as db:
        found = db.execute("select count(*) from app.users where email = 'second@company.com'")
        assert found.fetchone() == (0,)


def test_repeated_failed_sign_ins_block_that_email_only(api):
    email = "lena.fischer@nexo.example"
    for _ in range(MAX_FAILED_LOGINS - 1):
        assert login(api, email, "wrong").status_code == 401
    assert login(api, email, DEMO_PASSWORD).status_code == 200  # success clears the failures

    for _ in range(MAX_FAILED_LOGINS):
        assert login(api, email, "wrong").status_code == 401
    blocked = login(api, email, DEMO_PASSWORD)  # even the right password is refused now
    assert blocked.status_code == 429 and 0 < int(blocked.headers["Retry-After"]) <= 15 * 60
    assert login(api, "aiko.tanaka@nexo.example", DEMO_PASSWORD).status_code == 200

    for _ in range(MAX_FAILED_LOGINS):  # an unknown email is limited the same way
        assert login(api, "nobody@nexo.example", "wrong").status_code == 401
    assert login(api, "nobody@nexo.example", "wrong").status_code == 429

    with psycopg.connect(api.url) as db:  # move the failures out of the window
        db.execute("update app.login_attempts set at = now() - interval '16 minutes'")
    assert login(api, email, DEMO_PASSWORD).status_code == 200


def test_usage_by_feature_adds_up_to_the_account_totals(api):
    usage = api.viewer.get(f"/accounts/{ACME}/usage").json()
    assert usage["usage_status"] == "ok"
    features = {f["feature"]: f for f in usage["features"]}
    assert sum(f["events_prior_30d"] for f in features.values()) == 1500
    assert sum(f["events_last_30d"] for f in features.values()) == 900
    # Acme stopped importing after its import ticket was opened, 38 days ago.
    assert features["import"]["events_last_30d"] == 0 and features["import"]["usage_change"] == -1.0
    assert features["login"]["users_last_30d"] > 0

    days = {d["day"] for d in usage["daily"]}
    assert len(days) <= 60 and max(days) == usage["as_of_day"]
    assert sum(d["events"] for d in usage["daily"]) == 2400
    assert usage["checks"]["failed"] == 0 and len(usage["freshness"]) == 5

    unlinked = api.viewer.get("/accounts/acct_0006/usage").json()
    assert unlinked["usage_status"] == "no_linked_workspace"
    assert (unlinked["features"], unlinked["daily"]) == ([], [])
    assert api.viewer.get("/accounts/nope/usage").status_code == 404


def test_parallel_guesses_cannot_get_past_the_limit(api):
    from concurrent.futures import ThreadPoolExecutor

    email = "daniel.reyes@nexo.example"
    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(lambda _: login(api, email, "wrong").status_code, range(12)))
    assert codes.count(401) == MAX_FAILED_LOGINS and codes.count(429) == 12 - MAX_FAILED_LOGINS
