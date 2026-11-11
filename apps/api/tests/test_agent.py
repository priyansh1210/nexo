"""The agent's rules hold whatever the model does, and the chat routes are private per user."""

import psycopg
import pytest
from psycopg.rows import dict_row

from apps.api.agent import graph, tools
from data.pipelines import runner
from data.synthetic.generate import ACME


class Scripted:
    """A provider that makes fixed tool calls, then gives a fixed answer: here, a misbehaving one."""

    def __init__(self, calls: list[dict], answer: dict):
        self.calls, self.answer = calls, answer

    def step(self, state, must_answer=False):
        if not state.get("calls") and not must_answer:
            return {"calls": self.calls}
        return {"answer": self.answer}


def ask(db, provider, question="What is going on?") -> dict:
    return graph.ask(graph.build(), db, provider, "test", question)


@pytest.fixture
def db(warehouse, request):
    copy = warehouse.copy(f"agent_{request.node.name[:40].lower()}")
    with psycopg.connect(copy.url, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def test_every_model_with_a_warehouse_check_is_declared_by_a_tool_group(db):
    checked = {r["model"] for r in db.execute("select distinct model from meta.check_results")}
    declared = set().union(*(models for _, models in tools.GROUPS.values()))
    assert checked and checked <= declared, sorted(checked - declared)


def test_a_model_that_invents_a_figure_has_that_claim_dropped(db):
    invented = "Acme Corp's usage dropped 57% this month."
    provider = Scripted(
        [{"name": "list_renewals", "args": {"window": "next_month", "at_risk_only": True}}],
        {
            "summary": invented,
            "observations": [
                {"text": invented, "evidence": ["c1"]},
                {"text": "Acme Corp renews next month.", "evidence": ["c1"]},
                {"text": "Nobody checked this.", "evidence": []},
            ],
            "hypotheses": [{"text": "Maybe 3 of 9 admins left.", "evidence": ["c1"]}],
        },
    )
    answer = ask(db, provider)
    assert [o["text"] for o in answer["observations"]] == ["Acme Corp renews next month."]
    assert answer["summary"] == "Acme Corp renews next month."  # the invented summary is replaced
    reasons = [d["reason"] for d in answer["dropped_claims"]]
    assert reasons.count("numbers not in the data: 57") == 2 and "cites no tool result" in reasons
    assert answer["hypotheses"] == []  # 9 is in no tool result
    assert "57" not in str({k: v for k, v in answer.items() if k != "dropped_claims"})


def test_a_model_cannot_state_the_usage_trend_while_usage_data_is_stale(db):
    runner.stall(db, "product_events", hours=48)
    provider = Scripted(
        [{"name": "get_usage", "args": {"account_id": ACME}}],
        {
            "summary": "Usage fell 40%.",
            "observations": [{"text": "Usage fell 40% (1500 events to 900).", "evidence": ["c1"]}],
            "hypotheses": [],
        },
    )
    answer = ask(db, provider)
    assert answer["observations"] == [] and len(answer["dropped_claims"]) == 2
    assert answer["data_notes"][0].startswith("Usage data has not refreshed for 2 days.")
    usage = tools.get_usage(db, ACME)
    assert usage["rows"][0]["events_last_30d"] is None and usage["withheld"][0][
        "reason"
    ].startswith("Usage data")


def test_tools_refuse_bad_input_without_breaking_the_conversation(db):
    assert tools.run(db, "drop_tables", {})["error"] == "There is no tool named drop_tables."
    assert (
        "Unknown arguments" in tools.run(db, "get_usage", {"account_id": ACME, "sql": "x"})["error"]
    )
    assert "could not run" in tools.run(db, "get_usage", {})["error"]
    assert tools.run(db, "find_account", {"name": "acme"})["rows"][0]["account_id"] == ACME
    assert tools.run(db, "get_usage", {"account_id": "nope"})["rows"] == []


def test_ticket_text_is_marked_as_customer_written(db):
    hestria = tools.find_account(db, "Hestria")["rows"][0]["account_id"]
    result = tools.get_tickets(db, hestria)
    assert result["untrusted_fields"] == ["subject", "body"]
    assert any("Ignore all previous instructions" in t["body"] for t in result["rows"])


def test_document_search_ranks_the_matching_note_first(db):
    found = tools.search_documents(db, ACME, "import failing column mapping")["rows"]
    assert found[0]["title"] == "Onboarding check-in"


def test_chat_answers_follow_ups_and_keeps_conversations_private(api):
    first = api.csm.post(
        "/conversations/renewals-1/messages", json={"message": "Which renewals need attention?"}
    )
    assert first.status_code == 200
    assert first.json()["summary"].startswith("3 accounts renewing next month need attention.")
    second = api.csm.post(
        "/conversations/renewals-1/messages", json={"message": "Investigate Acme."}
    ).json()
    assert second["hypotheses"] and second["evidence"]["c2"]["link"] == f"/accounts/{ACME}"
    assert {s["source"] for s in second["evidence"]["c2"]["sources"]} >= {"crm"}  # with its age

    history = api.csm.get("/conversations/renewals-1").json()
    assert [h["question"] for h in history] == [
        "Which renewals need attention?",
        "Investigate Acme.",
    ]
    assert api.viewer.get("/conversations/renewals-1").json() == []  # another user sees nothing

    assert (
        api.anonymous.post("/conversations/x/messages", json={"message": "hi"}).status_code == 401
    )
    assert (
        api.csm.post("/conversations/bad%20id/messages", json={"message": "hi"}).status_code == 422
    )
    assert api.csm.post("/conversations/x/messages", json={"message": "  "}).status_code == 422


def test_a_model_that_never_stops_asking_for_tools_gets_a_plain_answer(db):
    class Endless:
        def step(self, state, must_answer=False):
            return {"calls": [{"name": "get_freshness", "args": {}}]}

    answer = ask(db, Endless())
    assert len(answer["tool_calls"]) == graph.MAX_TOOL_CALLS
    assert answer["summary"].startswith("I reached my limit of lookups")


def test_numbers_written_with_thousands_separators_are_read_whole(db):
    provider = Scripted(
        [{"name": "get_usage", "args": {"account_id": ACME}}],
        {
            "summary": "Usage fell.",
            "observations": [{"text": "Acme logged 1,500 events, then 900.", "evidence": ["c1"]}],
            "hypotheses": [],
        },
    )
    answer = ask(db, provider)
    assert answer["dropped_claims"] == [] and len(answer["observations"]) == 1


def test_a_badly_formed_answer_is_dropped_not_a_crash():
    # Only Claude's API enforces the answer's shape; a small local model may send anything.
    draft = {
        "summary": ["not text"],
        "observations": [{"evidence": ["c1"]}, "loose text", {"text": "Fine.", "evidence": None}],
        "hypotheses": "not a list",
    }
    answer, dropped = graph.check(draft, [], "What is going on?")
    assert answer == {"summary": "", "observations": [], "hypotheses": []}
    assert [d["reason"] for d in dropped] == ["not a claim", "not a claim", "cites no tool result"]


def test_a_draft_that_quotes_a_number_not_in_the_data_is_dropped(db):
    body = "Usage fell 73% this month."
    provider = Scripted(
        [{"name": "draft_note", "args": {"account_id": ACME, "body": body}}],
        {"summary": "Drafted.", "observations": [], "hypotheses": []},
    )
    answer = ask(db, provider)
    assert answer["drafts"] == []
    assert answer["dropped_claims"] == [{"text": body, "reason": "numbers not in the data: 73"}]


def test_a_redrafted_action_becomes_one_proposal_not_two(db):
    provider = Scripted(
        [
            {"name": "draft_note", "args": {"account_id": ACME, "body": "First try."}},
            {"name": "draft_note", "args": {"account_id": ACME, "body": "Better wording."}},
        ],
        {"summary": "Drafted.", "observations": [], "hypotheses": []},
    )
    [draft] = ask(db, provider)["drafts"]
    assert draft["params"]["body"] == "Better wording."


def test_records_set_aside_lately_are_disclosed():
    source = {
        "source": "product_events",
        "label": "Usage data",
        "status": "fresh",
        "age_hours": 1,
        "rejected_last_day": 3,
    }
    notes = graph.data_notes([{"result": {"sources": [source]}}])
    expected = (
        "Usage data: 3 records in the last day could not be read and were set aside, so its "
        "totals may be slightly low."
    )
    assert notes == [expected]
