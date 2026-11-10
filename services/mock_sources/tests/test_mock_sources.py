from fastapi.testclient import TestClient

from data.synthetic.generate import ACME
from services.mock_sources import main

client = TestClient(main.app)


def test_reads_account_and_contacts():
    assert client.get(f"/crm/accounts/{ACME}").json()["name"] == "Acme Corp"
    roles = {c["role"] for c in client.get(f"/crm/accounts/{ACME}/contacts").json()}
    assert roles == {"admin", "champion", "billing"}
    assert client.get("/crm/accounts/nope").status_code == 404
    assert client.get("/crm/accounts/nope/contacts").status_code == 404


def test_a_ticket_change_shows_on_the_next_read():
    ticket_id = next(t["ticket_id"] for t in main.tickets.values() if "import" in t["subject"])
    assert client.get(f"/helpdesk/tickets/{ticket_id}").json()["status"] == "open"

    assert (
        client.patch(f"/helpdesk/tickets/{ticket_id}", json={"status": "solved"}).status_code == 200
    )
    after = client.get(f"/helpdesk/tickets/{ticket_id}").json()
    assert after["status"] == "solved" and after["solved_at"]

    assert (
        client.patch(f"/helpdesk/tickets/{ticket_id}", json={"status": "deleted"}).status_code
        == 422
    )
    assert client.get("/helpdesk/tickets/nope").status_code == 404
