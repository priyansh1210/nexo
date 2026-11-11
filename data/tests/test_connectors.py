"""Connectors in isolation, against fake sources: no database needed."""

import httpx

from data.connectors import HelpdeskApi


def test_a_ticket_changed_in_the_same_second_as_the_last_read_is_not_missed():
    tickets = [{"ticket_id": "t1", "updated_at": "2026-11-11T10:00:00Z"}]

    def helpdesk(request: httpx.Request) -> httpx.Response:
        since = request.url.params["updated_since"]  # at or after, as the helpdesk API answers
        return httpx.Response(200, json=[t for t in tickets if t["updated_at"] >= since])

    connector = HelpdeskApi(
        httpx.Client(base_url="http://fake", transport=httpx.MockTransport(helpdesk))
    )
    first = connector.read("support_tickets", None)
    assert [t["ticket_id"] for t in first.records] == ["t1"]

    tickets.append({"ticket_id": "t2", "updated_at": "2026-11-11T10:00:00Z"})  # same second, later
    second = connector.read("support_tickets", first.cursor)
    assert [t["ticket_id"] for t in second.records] == ["t2"]  # t1 is not landed again

    third = connector.read("support_tickets", second.cursor)
    assert third.records == [] and third.cursor == second.cursor
