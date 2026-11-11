"""The conversation graph: investigate with read tools, then answer, then check the answer.

    investigate --(provider asks for tools)--> investigate
    investigate --(provider answers, or the tool budget is spent)--> finish --> end

`finish` does not trust the provider. It:
- drops any claim with a number that is not in a tool result it cites (the model must not compute or
  invent figures), and any observation that cites no tool call;
- adds the data notes itself, from the tool envelopes, so a stale source is always disclosed;
- attaches the evidence and the tool trace.

Conversations are saved by the LangGraph checkpointer, one thread per user and conversation, so a
follow-up question ("Investigate Acme") is answered with the earlier turns available.
"""

import json
import re
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, StateGraph

from apps.api.agent import tools

MAX_TOOL_CALLS = 8
# "1,500" is one number, not "1" and "500".
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
EFFECTS = {
    "product_events": "I can review support and renewal information, but I cannot reliably assess the "
    "latest usage trend.",
    "support_tickets": "I cannot reliably say which tickets are still open.",
    "crm": "Account details such as owner and renewal date may be out of date.",
    "billing": "I cannot reliably say whether invoices are overdue.",
    "documents": "Recent meeting notes and emails may be missing.",
}


class Turn(TypedDict, total=False):
    question: str
    history: list[dict]  # earlier turns: question and summary
    calls: list[dict]  # this turn's tool calls: id, name, args, result
    transcript: list[dict]  # the provider's own messages for this turn, if it keeps any
    draft: dict | None  # the provider's answer, before checking
    answer: dict | None  # the checked answer


def _numbers(text: str) -> set[str]:
    found = (n.replace(",", "") for n in NUMBER.findall(text))
    return {str(Decimal(n).normalize()) if "." in n else str(int(n)) for n in found}


def _supported(calls: list[dict], question: str) -> set[str]:
    """Every number a claim may quote: those in the tool results, their row counts, and the question."""
    found = _numbers(question)
    for call in calls:
        # Rows and totals only: timestamps elsewhere in a result would let almost any number through.
        quotable = [call["result"].get("rows", []), call["result"].get("totals", {})]
        found |= _numbers(json.dumps(quotable, default=str))
        found.add(str(len(call["result"].get("rows", []))))
    return found


def check(draft: dict, calls: list[dict], question: str) -> tuple[dict, list[dict]]:
    """Keep the claims the tool results support. Returns the checked answer and what was dropped."""
    by_id = {c["id"]: c for c in calls}
    anywhere = _supported(calls, question)
    kept, dropped = {"observations": [], "hypotheses": []}, []
    for kind in ("observations", "hypotheses"):
        for claim in draft.get(kind) or []:
            cited = [by_id[i] for i in claim.get("evidence", []) if i in by_id]
            allowed = _supported(cited, question) if kind == "observations" else anywhere
            unsupported = sorted(_numbers(claim["text"]) - allowed)
            if kind == "observations" and not cited:
                dropped.append({"text": claim["text"], "reason": "cites no tool result"})
            elif unsupported:
                dropped.append(
                    {
                        "text": claim["text"],
                        "reason": f"numbers not in the data: {', '.join(unsupported)}",
                    }
                )
            else:
                kept[kind].append({"text": claim["text"], "evidence": [c["id"] for c in cited]})
    summary = draft.get("summary") or ""
    if unsupported := sorted(_numbers(summary) - anywhere):
        dropped.append(
            {"text": summary, "reason": f"numbers not in the data: {', '.join(unsupported)}"}
        )
        summary = (
            kept["observations"][0]["text"] if kept["observations"] else "See the findings below."
        )
    return {"summary": summary, **kept}, dropped


def data_notes(calls: list[dict]) -> list[str]:
    """One plain sentence per problem with the data behind this answer."""
    notes = {}
    for call in calls:
        result = call["result"]
        for source in result.get("sources", []):
            if source["status"] != "fresh" and source["source"] not in notes:
                age = source["age_hours"]
                when = (
                    f"has not refreshed for {tools.age_words(age)}"
                    if age is not None
                    else "has never been loaded"
                )
                notes[source["source"]] = f"{source['label']} {when}. {EFFECTS[source['source']]}"
        for held in result.get("withheld", []):
            if held["reason"].startswith("the warehouse check"):
                notes.setdefault(
                    held["reason"],
                    f"{held['reason'].capitalize()}, so I have left out: {', '.join(held['fields'])}.",
                )
    return list(notes.values())


def investigate(state: Turn, config) -> Turn:
    db, provider = config["configurable"]["db"], config["configurable"]["provider"]
    calls = list(state.get("calls") or [])
    out_of_calls = len(calls) >= MAX_TOOL_CALLS
    step = provider.step(state, must_answer=out_of_calls)
    transcript = step.get("transcript", state.get("transcript") or [])
    if "answer" in step:
        return {"draft": step["answer"], "transcript": transcript}
    if out_of_calls:  # told to answer, it asked for more tools: stop rather than loop
        summary = "I reached my limit of lookups before finishing, so I have no answer yet."
        return {
            "draft": {"summary": summary, "observations": [], "hypotheses": []},
            "transcript": transcript,
        }
    for call in step["calls"][: MAX_TOOL_CALLS - len(calls)]:
        call_id = call.get("id") or f"c{len(calls) + 1}"
        calls.append(
            {
                "id": call_id,
                "name": call["name"],
                "args": call["args"],
                "result": tools.run(db, call["name"], call["args"]),
            }
        )
    return {"calls": calls, "transcript": transcript}


def finish(state: Turn) -> Turn:
    calls = state.get("calls") or []
    answer, dropped = check(state["draft"], calls, state["question"])
    answer |= {
        "data_notes": data_notes(calls),
        "evidence": {
            c["id"]: {"tool": c["name"], **(c["result"].get("evidence") or [{}])[0]} for c in calls
        },
        "tool_calls": [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in calls],
        "dropped_claims": dropped,
    }
    history = [
        *(state.get("history") or []),
        {"question": state["question"], "summary": answer["summary"]},
    ]
    return {"answer": answer, "history": history[-10:]}


def build(checkpointer=None):
    graph = StateGraph(Turn)
    graph.add_node("investigate", investigate)
    graph.add_node("finish", finish)
    graph.set_entry_point("investigate")
    graph.add_conditional_edges(
        "investigate", lambda s: "finish" if s.get("draft") else "investigate"
    )
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def ask(graph, db, provider, thread_id: str, question: str) -> dict:
    """One user message in, one checked answer out. The thread's earlier turns are kept."""
    start = {"question": question, "calls": [], "transcript": [], "draft": None, "answer": None}
    config = {
        "configurable": {"thread_id": thread_id, "db": db, "provider": provider},
        "recursion_limit": 25,
    }
    return graph.invoke(start, config)["answer"]
