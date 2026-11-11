"""Runs the evaluation scenarios in evals/scenarios.yaml against a database and a provider."""

from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from apps.api import actions
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
    # Every turn: no action is proposed unless the scenario expects it.
    proposed = [{"action": p["action"], "status": p["status"]} for p in answer["proposals"]]
    if proposed != expect.get("proposals", []):
        found.append(f"proposals {proposed} != {expect.get('proposals', [])}")
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


def decided(db, sources, user: dict, proposals: list[dict], turn: dict) -> list[str]:
    """Change the live records if the turn says so, then decide every proposal and check how."""
    found = []
    for proposal in proposals:
        if status := turn.get("change_ticket"):
            ticket = proposal["params"]["ticket_id"]
            sources.patch(f"/helpdesk/tickets/{ticket}", json={"status": status}).raise_for_status()
        decision = actions.Decision(decision=turn["decide"])
        result, _ = actions.decide(db, sources, user, proposal["proposal_id"], decision)
        expect = turn.get("outcome", {})
        if result["status"] != expect.get("status"):
            found.append(f"decision status {result['status']} != {expect.get('status')}")
        said = " ".join(result["outcome"].get("changes", []))
        found += [f"outcome missing {t!r}" for t in expect.get("mentions", []) if t not in said]
    return found


def run(url: str, scenario: dict, provider, sources, compiled=None) -> list[str]:
    """Run one scenario's turns in one conversation. Returns its failures, empty when it passed.

    `sources` is the live source service an approved action rechecks. The database must hold the
    application tables and demo users (the API's migrations).
    """
    setup(url, scenario.get("setup", {}))
    compiled = compiled or graph.build()
    problems = []
    with psycopg.connect(url, row_factory=dict_row) as db:
        email = scenario.get("as", "maya.okafor@nexo.example")  # the demo CSM who owns Acme
        user = db.execute("select * from app.users where email = %s", (email,)).fetchone()
        for number, turn in enumerate(scenario["turns"], 1):
            # Without a checkpointer the graph keeps no history, so each turn starts clean.
            answer = graph.ask(compiled, db, provider, f"eval-{scenario['name']}", turn["ask"])
            answer["proposals"] = actions.save(db, user, scenario["name"], answer.pop("drafts"))
            problems += [f"turn {number}: {p}" for p in failures(answer, turn.get("expect", {}))]
            if "decide" in turn:
                found = decided(db, sources, user, answer["proposals"], turn)
                problems += [f"turn {number}: {p}" for p in found]
            db.commit()
        # The phase gate: no action ever ran without an approval before it.
        unapproved = db.execute(
            "select count(*) as n from audit.events e where e.action = 'action.executed' and not "
            "exists (select 1 from audit.events a where a.action = 'action.approved' "
            "and a.target_id = e.target_id and a.event_id < e.event_id)"
        ).fetchone()["n"]
        if unapproved:
            problems.append(f"{unapproved} actions ran without an approval")
    return problems
