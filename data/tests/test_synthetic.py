from collections import Counter
from datetime import date, timedelta

import pytest

from data.synthetic.generate import ACME, CSV_TABLES, generate, write

AS_OF = date(2026, 11, 10)
DATA = generate(seed=7, as_of=AS_OF)  # shared by the read-only tests below


def usage(data: dict, as_of: date) -> dict[str, tuple[int, int]]:
    """Per account: (events in the prior 30 days, events in the last 30 days), duplicates removed."""
    account_of = {a["workspace_id"]: a["account_id"] for a in data["accounts"] if a["workspace_id"]}
    counts: Counter = Counter()
    seen = set()
    for event in data["events"]:
        account = account_of.get(event["workspace_id"])
        if event["event_id"] in seen or event["name"] == "onboarding_step" or not account:
            continue
        seen.add(event["event_id"])
        days_back = (as_of - date.fromisoformat(event["occurred_at"][:10])).days
        if 1 <= days_back <= 60:
            counts[account, days_back <= 30] += 1
    return {a: (counts[a, False], counts[a, True]) for a in account_of.values()}


def at_risk(data: dict, as_of: date) -> dict[str, float]:
    """Accounts renewing next calendar month that match a risk rule, with their usage change."""
    next_month = (as_of.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
    stale = (as_of - timedelta(days=14)).isoformat()
    old_open_tickets = {
        t["org_id"]
        for t in data["tickets"]
        if t["status"] == "open" and t["severity"] in ("high", "urgent") and t["created_at"] < stale
    }
    overdue = {i["account_id"] for i in data["invoices"] if i["status"] == "overdue"}
    result, counts = {}, usage(data, as_of)
    for account in data["accounts"]:
        prior, last = counts.get(account["account_id"], (0, 0))
        change = last / prior - 1 if prior else 0.0
        risky = (
            change <= -0.2
            or account["support_org_id"] in old_open_tickets
            or account["account_id"] in overdue
        )
        if account["renewal_date"].startswith(next_month) and risky:
            result[account["account_id"]] = change
    return result


def test_same_seed_and_date_give_identical_files(tmp_path):
    for run in ("a", "b"):
        write(generate(seed=7, as_of=AS_OF), tmp_path / run)
    for name in ("accounts", "contacts", "invoices", "tickets", "documents", "events"):
        file = f"{name}.{'csv' if name in CSV_TABLES else 'jsonl'}"
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes(), file
    assert generate(seed=8, as_of=AS_OF)["events"] != DATA["events"]


# The story must hold on any day the demo runs, including month ends and a year rollover.
@pytest.mark.parametrize("as_of", [AS_OF, date(2026, 12, 31), date(2027, 3, 1)])
def test_three_renewals_are_at_risk_and_acme_fell_most(as_of):
    data = generate(seed=7, as_of=as_of)
    risky = at_risk(data, as_of)
    assert len(risky) == 3
    assert min(risky, key=risky.get) == ACME
    assert usage(data, as_of)[ACME] == (1500, 900)  # exactly -40%


def test_acme_story_facts():
    data = DATA
    acme = next(a for a in data["accounts"] if a["account_id"] == ACME)
    admin = next(c for c in data["contacts"] if c["account_id"] == ACME and c["role"] == "admin")

    ticket = next(t for t in data["tickets"] if "import" in t["subject"].lower())
    assert ticket["org_id"] == acme["support_org_id"]
    assert (ticket["status"], ticket["severity"]) == ("open", "high")
    assert ticket["requester_email"] == admin["email"]
    opened = ticket["created_at"][:10]
    assert opened == (AS_OF - timedelta(days=38)).isoformat()

    notes = [d["body"] for d in data["documents"] if d["account_id"] == ACME]
    assert any("import keeps failing" in body for body in notes)

    acme_events = [e for e in data["events"] if e["workspace_id"] == acme["workspace_id"]]
    import_days = [
        e["occurred_at"][:10] for e in acme_events if e["properties"].get("feature") == "import"
    ]
    assert import_days and max(import_days) < opened  # import was used, then stopped at the ticket
    steps = {e["properties"]["step"] for e in acme_events if e["name"] == "onboarding_step"}
    assert steps == {"kickoff", "admin_setup", "team_invited"}  # never reached data_import


def test_data_has_duplicates_and_one_unlinked_workspace():
    data = DATA
    ids = [e["event_id"] for e in data["events"]]
    assert len(ids) > len(set(ids))

    unlinked = [a for a in data["accounts"] if not a["workspace_id"]]
    assert len(unlinked) == 1
    linked = {a["workspace_id"] for a in data["accounts"]}
    assert len({e["workspace_id"] for e in data["events"]} - linked) == 1
