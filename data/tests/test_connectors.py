"""Connectors in isolation, against fake sources: no database needed."""

import json

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


def test_the_event_log_reads_new_whole_lines_and_sets_bad_ones_aside(tmp_path):
    from data.connectors import EventLog

    good = {
        "workspace_id": "w",
        "user_id": "u",
        "name": "login",
        "occurred_at": "2026-11-11T10:00:00Z",
    }
    log = tmp_path / "events.jsonl"
    log.write_text(
        json.dumps(good) + "\n" + "not json\n" + '{"name": "login"}\n' + '{"half', "utf-8"
    )
    events = EventLog(log)

    first = events.read("product_events", None)
    assert first.records == [good]
    assert [r["record"] for r in first.rejected] == ["not json", '{"name": "login"}']
    assert "missing" in first.rejected[1]["error"]

    with log.open("a", encoding="utf-8") as more:  # the half-written line is finished
        more.write(' line": 1}\n')
    second = events.read("product_events", first.cursor)
    assert second.records == [] and len(second.rejected) == 1  # read once it ended, not before
    assert events.read("product_events", second.cursor).records == []

    # A cursor saved before byte offsets counted lines; it resumes at the same place.
    assert events.read("product_events", "1").rejected == first.rejected + second.rejected
