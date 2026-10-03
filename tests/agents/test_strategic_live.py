"""Strategic rules across real branch stacking and replay, using a deterministic model."""
from __future__ import annotations

import json

import pytest

from agents.match import Match, load_match, replay
from agents.match_board import LabBoard
from agents.game_rules import read_game
from tests.agents.conftest import turingdb_reachable

pytestmark = pytest.mark.skipif(not turingdb_reachable(), reason="live theatre unavailable")


class PlanningModel:
    model = "deterministic-planning-test"

    def chat(self, messages, **kwargs):
        prompt = messages[1]["content"]
        opts = json.loads(prompt.split("OPTIONS (current state):\n", 1)[1].split("\n\nReply", 1)[0])
        candidate = opts["deep_candidates"][0]
        return json.dumps({"thought": "Compare future exposure within the remaining budget.",
                           "action": candidate["action"], "args": candidate["args"]})


def test_strategic_match_and_replay_preserve_clock_budget_and_scores(lab, tmp_path):
    board = LabBoard(lab)
    match = Match(board, rounds=4, strategic=True, seed=7, llm=PlanningModel(),
                  directory=tmp_path, save_as="strategic")
    summary = match.run()
    assert summary["status"] == "done", [e for e in match.events if e["type"] == "error"]
    blue = [m for m in match.moves if m.side == "blue"]
    assert len(blue) == 5 and blue[0].round == 0
    assert summary["budget_remaining"] == 14 - sum(m.strategy["cost"] for m in blue)
    assert 0 <= summary["budget_remaining"] <= 14
    assert summary["cumulative_loss"] == pytest.approx(sum(max(0, m.loss_pct) * 0.5 for m in match.moves
                                                          if m.side in ("red", "blue") and m.round > 0), abs=0.1)
    assert len(summary["round_scores"]) == 4
    assert len(summary["missions"]) == 3
    assert any(m.strategy.get("planning") for m in match.moves)
    assert any(m.strategy.get("event_active") for m in match.moves)
    assert any(m.strategy.get("alternatives") for m in match.moves)
    assert all(m.actions[0]["action"] == "game_order" for m in blue)
    red = [m.action for m in match.moves if m.side == "red"]
    assert all(action not in red[max(0, i - 2):i] for i, action in enumerate(red))
    assert not any(r.label.startswith("Planning") or r.label == "Opponent preview" for r in lab.records())
    recorded_game = read_game(lab.graph.session(match.head))
    final_loss = board.loss(match.head)
    events = []
    replay(load_match("strategic", tmp_path), board, lambda kind, data: events.append((kind, data)),
           speed=100000, sleep=lambda _: None)
    last = [data for kind, data in events if kind == "move"][-1]
    assert read_game(lab.graph.session(last["branch_id"])) == recorded_game
    assert board.loss(last["branch_id"]) == pytest.approx(final_loss)
    assert "GameState" not in lab.graph.session("main").labels
