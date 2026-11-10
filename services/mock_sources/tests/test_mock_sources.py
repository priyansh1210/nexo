from datetime import date

from fastapi.testclient import TestClient

from data.synthetic.generate import ACME, generate
from services.mock_sources.main import create_app, load

DATA = generate(seed=7, as_of=date(2026, 11, 10))
IMPORT_TICKET = next(t["ticket_id"] for t in DATA["tickets"] if "import" in t["subject"])


def test_reads_account_and_contacts():
    client = TestClient(create_app(DATA))
    assert client.get(f"/crm/accounts/{ACME}").json()["name"] == "Acme Corp"
    roles = {c["role"] for c in client.get(f"/crm/accounts/{ACME}/contacts").json()}
    assert roles == {"admin", "champion", "billing"}
    assert client.get("/crm/accounts/nope").status_code == 404
    assert client.get("/crm/accounts/nope/contacts").status_code == 404


def test_a_ticket_change_shows_on_the_next_read_and_in_the_changed_list():
    client = TestClient(create_app(DATA))
    assert client.get(f"/helpdesk/tickets/{IMPORT_TICKET}").json()["status"] == "open"
    assert len(client.get("/helpdesk/tickets").json()) == len(DATA["tickets"])
    newest = max(t["updated_at"] for t in DATA["tickets"])
    assert client.get("/helpdesk/tickets", params={"updated_since": newest}).json() == []

    changed = client.patch(f"/helpdesk/tickets/{IMPORT_TICKET}", json={"status": "solved"})
    assert changed.status_code == 200
    after = client.get(f"/helpdesk/tickets/{IMPORT_TICKET}").json()
    assert after["status"] == "solved" and after["solved_at"]
    since = client.get("/helpdesk/tickets", params={"updated_since": newest}).json()
    assert [t["ticket_id"] for t in since] == [IMPORT_TICKET]

    bad = client.patch(f"/helpdesk/tickets/{IMPORT_TICKET}", json={"status": "deleted"})
    assert bad.status_code == 422
    assert client.get("/helpdesk/tickets/nope").status_code == 404


def test_a_restart_serves_the_data_first_written_to_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXO_DATA_DIR", str(tmp_path))
    first = load()
    assert (tmp_path / "events.jsonl").exists()

    # Pretend the first start happened on another day: a restart must rebuild that day's data.
    (tmp_path / "as_of.txt").write_text("2026-11-10")
    assert load()["accounts"] == DATA["accounts"]
    assert load()["accounts"] != first["accounts"] or date.today() == date(2026, 11, 10)
