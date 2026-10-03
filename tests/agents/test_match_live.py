"""The wargame engine on the live theatre graph with a fake LLM: real branches, no model calls.
Skipped unless a TuringDB server with the theatre graph is reachable."""

from __future__ import annotations

import json

import pytest

from agents.match import Match, load_match, replay
from agents.match_board import LabBoard
from tests.agents.conftest import turingdb_reachable
from tests.agents.test_match import FakeLLM

pytestmark = pytest.mark.skipif(not turingdb_reachable(), reason="TuringDB with the theatre graph is not running")

MANCHESTER = {"action": "wipe_bbox", "args": {"west": -2.3929, "south": 53.412, "east": -2.2329, "north": 53.532}}


@pytest.fixture(scope="module")
def board(lab):
    return LabBoard(lab)


def _plays_top_option(board: LabBoard, head: str) -> FakeLLM:
    """A fake model that plays the board's own top-ranked red option (valid on the live graph)."""
    red = board.options("red", head)["fallback"]
    return FakeLLM({"red": [json.dumps({"thought": "top-ranked target", **red})]})


def test_live_match_stacks_on_a_scenario_base_and_replays(board, tmp_path):
    base = board.rebuild("test Manchester", [MANCHESTER])
    base_loss = board.loss(base)
    assert base_loss > 0

    match = Match(board, base, 1, llm=_plays_top_option(board, base), directory=tmp_path, save_as="live")
    summary = match.run()
    assert summary["status"] == "done", match.events[-2:]
    red, blue = match.moves
    assert red.parent_id == base and blue.parent_id == red.branch_id
    assert red.abs_loss_pct == pytest.approx(100 * board.loss(red.branch_id), abs=0.1)
    assert red.loss_pct == pytest.approx(100 * (board.loss(red.branch_id) - base_loss), abs=0.1)
    assert blue.abs_loss_pct <= red.abs_loss_pct
    assert [a["action"] for a in board.lineage(blue.branch_id)] == ["wipe_bbox", red.action, blue.action]
    assert red.targets, "a red strike should name something to flash on the map"
    assert red.db_ms < 30_000, f"a move should take seconds, took {red.db_ms} ms of DB time"

    out: list[tuple[str, dict]] = []
    replay(load_match("live", tmp_path), board, lambda k, d: out.append((k, d)), speed=50)
    moves = [d for k, d in out if k == "move"]
    assert [m["side"] for m in moves] == ["red", "blue"]
    assert moves[-1]["branch_id"] != blue.branch_id
    assert board.loss(moves[-1]["branch_id"]) == pytest.approx(board.loss(blue.branch_id))
