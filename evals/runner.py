"""Runs the evaluation scenarios in evals/scenarios.yaml against a database and a provider."""

from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from apps.api.agent import graph
from data.pipelines import runner

SCENARIOS = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text(encoding="utf-8"))


def setup(url: str, steps: dict) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        if source := steps.get("stall"):
            runner.stall(conn, source, hours=48)
        if model := steps.get("fail_check"):
            assert model == "stg_tickets", "only a ticket check failure is scripted so far"
            bad = {
                "ticket_id": "tkt_eval_bad",
                "org_id": "org_eval",
                "severity": "catastrophic",  # not an accepted value
                "status": "open",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
            conn.execute(
                "insert into raw.support_tickets (payload, _source, _batch_id) "
                "values (%s, 'eval', gen_random_uuid())",
                (Jsonb(bad),),
            )
            runner.build(conn)


def text_of(answer: dict) -> str:
    parts = [answer["summary"], *answer["data_notes"]]
    parts += [c["text"] for c in answer["observations"] + answer["hypotheses"]]
    return "\n".join(parts)


def failures(answer: dict, expect: dict) -> list[str]:
    """What this answer got wrong against its expectations, plus the checks every turn must pass."""
    found, called = [], {c["name"] for c in answer["tool_calls"]}
    text = text_of(answer)
    if missing := set(expect.get("tools", [])) - called:
        found.append(f"tools not called: {sorted(missing)}")
    if "accounts" in expect:
        renewals = answer["evidence"].get(
            next((c["id"] for c in answer["tool_calls"] if c["name"] == "list_renewals"), ""), {}
        )
        if sorted(renewals.get("records", [])) != sorted(expect["accounts"]):
            found.append(f"accounts {renewals.get('records')} != {expect['accounts']}")
    found += [f"missing text: {t!r}" for t in expect.get("mentions", []) if t not in text]
    found += [f"forbidden text: {t!r}" for t in expect.get("not_mentions", []) if t in text]
    hypotheses = " ".join(h["text"] for h in answer["hypotheses"])
    found += [
        f"missing hypothesis: {t!r}"
        for t in expect.get("hypothesis_mentions", [])
        if t not in hypotheses
    ]
    notes = " ".join(answer["data_notes"])
    found += [f"missing data note: {t!r}" for t in expect.get("notes", []) if t not in notes]
    if expect.get("no_notes") and answer["data_notes"]:
        found.append(f"unexpected data notes: {answer['data_notes']}")
    # Every turn: each observation cites a tool call, and no claim was dropped for its numbers.
    found += [
        f"uncited observation: {o['text']!r}" for o in answer["observations"] if not o["evidence"]
    ]
    found += [f"dropped claim: {d}" for d in answer["dropped_claims"]]
    return found


def run(url: str, scenario: dict, provider, compiled=None) -> list[str]:
    """Run one scenario's turns in one conversation. Returns its failures, empty when it passed."""
    setup(url, scenario.get("setup", {}))
    compiled = compiled or graph.build()
    problems = []
    with psycopg.connect(url, row_factory=dict_row) as db:
        for number, turn in enumerate(scenario["turns"], 1):
            # Without a checkpointer the graph keeps no history, so each turn starts clean.
            answer = graph.ask(compiled, db, provider, f"eval-{scenario['name']}", turn["ask"])
            problems += [f"turn {number}: {p}" for p in failures(answer, turn.get("expect", {}))]
    return problems
