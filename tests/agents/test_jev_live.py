"""Hybrid Blue branch execution and replay against TuringDB, with deterministic provider doubles."""
from __future__ import annotations

import json

import pytest

from agents.blue_selection import BlueSelector
from agents.defence import run_defence
from agents.jev import JevSettings
from agents.tools import build_branch, build_stacked
from tests.agents.conftest import turingdb_reachable

pytestmark = pytest.mark.skipif(not turingdb_reachable(), reason="live theatre unavailable")


class ProposalModel:
    model = "deterministic-blue-test"

    def chat(self, messages, agent="agent", **kwargs):
        if agent == "blue_candidates":
            state = json.loads(messages[1]["content"])["state"]
            part = state["parts_unavailable"][0]
            return json.dumps({"action": "propose", "args": {"candidates": [
                {"action": "backup_all_affected_parts", "args": {"only_critical": True}},
                {"action": "backup_all_affected_parts", "args": {}},
                {"action": "add_backup_supplier", "args": {"part_id": part}},
            ]}})
        return json.dumps({"action": "finish", "args": {"explanation": "Restore critical parts first."}})


class ChoiceClient:
    def choose(self, state, candidates):
        assert "loss" not in json.dumps(state)
        return {"selected_id": "c1", "confidence": 0.6,
                "probabilities": {"c1": 0.6, "c2": 0.3, "c3": 0.1}, "request_ms": 0}


def test_hybrid_blue_preserves_main_lineage_and_replay(lab, monkeypatch):
    import agents.blue_selection as selection
    monkeypatch.setattr(selection, "BlueSelector", lambda: BlueSelector(JevSettings(enabled=True), ChoiceClient()))
    main_before = lab.graph.session("main").q("MATCH (n) RETURN count(n) AS c").iloc[0, 0]
    built = build_branch(lab, "threat", "Hybrid test abstract supplier outage",
                         [{"action": "strike_supplier", "args": {"supplier_id": "SUP012"}}])
    assert "error" not in built
    threat = str(built["change_id"])
    initial = {r.change_id for r in lab.records()}
    trace = run_defence(lab, ProposalModel(), threat)
    audit = trace.result["selection"]
    assert audit["selector"] == "jev" and not audit["fallback"]
    assert audit["total_llm_calls"] == 2 and audit["jev_calls"] == 1
    selected = str(trace.result["defence_branch"])
    added = [r for r in lab.records() if r.change_id not in initial]
    assert len(added) == 1 and added[0].change_id == selected  # previews removed
    spec = lab.spec_of(selected)
    assert spec["parent"] == threat
    assert spec["actions"][0]["action"] == "strike_supplier"
    assert spec["actions"][-1]["action"] == "propagate"
    countermeasures = trace.result["countermeasures"]
    assert len(countermeasures) == 1 and countermeasures[0]["args"] == {"only_critical": True}
    replayed = build_stacked(lab, "defence", "Hybrid replay", threat, countermeasures)
    assert "error" not in replayed
    assert replayed["loss_pct"] == trace.result["loss_after_pct"]
    assert lab.graph.session("main").q("MATCH (n) RETURN count(n) AS c").iloc[0, 0] == main_before


@pytest.mark.skipif(
    "strategic" not in __import__("inspect").signature(__import__("agents.match", fromlist=["Match"]).Match).parameters,
    reason="strategic wargame extension is not installed",
)
def test_strategic_match_keeps_budget_one_action_and_preview_cleanup(lab, monkeypatch, tmp_path):
    import agents.blue_selection as selection
    from agents.match import Match
    from agents.match_board import LabBoard

    class Model:
        model = "deterministic-hybrid-match"
        def chat(self, messages, agent="agent", **kwargs):
            if agent == "blue_candidates":
                offered = json.loads(messages[1]["content"])["offered"]
                return json.dumps({"action": "propose", "args": {"candidates": [c["id"] for c in offered[:3]]}})
            if agent == "blue_explanation":
                return json.dumps({"action": "finish", "args": {"explanation": "Respect remaining credits and priorities."}})
            opts = json.loads(messages[1]["content"].split("OPTIONS (current state):\n", 1)[1].split("\n\nReply", 1)[0])
            c = opts["deep_candidates"][0]
            return json.dumps({"thought": "Use a legal plan.", "action": c["action"], "args": c["args"]})

    class Classifier:
        def choose(self, state, candidates):
            n = len(candidates)
            return {"selected_id": candidates[0]["id"], "confidence": 1 / n,
                    "probabilities": {c["id"]: 1 / n for c in candidates}, "request_ms": 0}

    monkeypatch.setattr(selection, "BlueSelector", lambda: BlueSelector(JevSettings(enabled=True), Classifier()))
    board = LabBoard(lab)
    match = Match(board, rounds=1, strategic=True, llm=Model(), directory=tmp_path)
    result = match.run()
    assert result["status"] == "done", [e for e in match.events if e["type"] == "error"]
    blue = [m for m in match.moves if m.side == "blue"]
    assert len(blue) == 2
    assert any(m.selection.get("selector") == "jev" for m in blue)
    assert all(len(m.actions) == 1 and m.actions[0]["action"] == "game_order" for m in blue)
    assert result["budget_remaining"] == 14 - sum(m.strategy["cost"] for m in blue)
    assert not any(r.label.startswith("Planning") or r.label == "Opponent preview" for r in lab.records())
    assert "GameState" not in lab.graph.session("main").labels
