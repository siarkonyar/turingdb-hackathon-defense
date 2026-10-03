"""Offline tests for the wargame engine: a fake LLM and a fake board (no TuringDB, no network)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from agents.match import InjectResult, Match, MoveRejected, list_matches, load_match, match_path, replay
from agents.match_prompts import describe_action

# projected-loss effect of each action on the fake board
EFFECT = {"strike_supplier": 0.10, "strike_plant": 0.07, "cut_route": 0.04, "wipe_bbox": 0.20,
          "backup_all_affected_parts": -0.06, "restore_power": -0.03}


class FakeBoard:
    def __init__(self) -> None:
        self.branches: dict[str, dict] = {"main": {"parent": None, "actions": []}}
        self.next_id = 100

    def add_base(self, branch: str, actions: list[dict]) -> None:
        self.branches[branch] = {"parent": "main", "actions": actions}

    def loss(self, branch: str) -> float:
        return max(0.0, sum(EFFECT.get(a["action"], 0.0) for a in self.branches[branch]["actions"]))

    def stack(self, side: str, label: str, parent: str, actions: list[dict]) -> str:
        if any((a.get("args") or {}).get("supplier_id") == "BAD" for a in actions):
            raise MoveRejected("no Supplier with supplier_id 'BAD'")
        branch = str(self.next_id)
        self.next_id += 1
        self.branches[branch] = {"parent": parent, "actions": self.branches[parent]["actions"] + actions}
        return branch

    def options(self, side: str, head: str) -> dict:
        if side == "red":
            return {"names": {"SUP001": "Acme"}, "fallback": {"action": "strike_supplier",
                                                               "args": {"supplier_id": "SUP001"}},
                    "alternates": [{"action": "strike_plant", "args": {"gppd_idnr": "W1"}}]}
        return {"names": {"SUP001": "Acme"}, "fallback": {"action": "backup_all_affected_parts", "args": {}}}

    def effects(self, side: str, parent: str, child: str, actions: list[dict]) -> dict:
        return {"targets": [{"id": "1", "name": "x", "kind": "supplier", "lat": 53.0, "lon": -2.0}], "arcs": []}

    def query(self, branch: str, cypher: str) -> dict:
        return {"rows": [{"n": 1}], "row_count": 1}

    def lineage(self, branch: str) -> list[dict]:
        return list(self.branches[branch]["actions"])

    def rebuild(self, label: str, actions: list[dict]) -> str:
        return self.stack("inject", label, "main", actions) if actions else "main"


class FakeLLM:
    """Replies with a scripted JSON action per side; records every prompt it saw."""

    model = "fake-model"

    def __init__(self, script: dict[str, list[str]] | None = None) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[tuple[str, list[dict]]] = []

    def chat(self, messages, agent="agent", **_):
        self.calls.append((agent, [dict(m) for m in messages]))
        queue = self.script.get(agent)
        if queue:
            return queue.pop(0)
        if agent == "red":
            if '"not_allowed_this_turn": "strike_supplier"' in messages[-1]["content"]:  # red must vary its moves
                return json.dumps({"thought": "hit the plant instead", "action": "strike_plant",
                                   "args": {"gppd_idnr": "W1"}})
            return json.dumps({"thought": "hit the top supplier", "action": "strike_supplier",
                               "args": {"supplier_id": "SUP001"}})
        return json.dumps({"thought": "close every gap", "action": "backup_all_affected_parts", "args": {}})


def fake_injector(board: FakeBoard):
    def inject(text: str, parent: str, llm) -> InjectResult:
        step = {"action": "wipe_bbox", "args": {"west": -3.1, "south": 53.3, "east": -2.9, "north": 53.5}}
        return InjectResult(branch_id=board.stack("inject", f"Event: {text}", parent, [step]), actions=[step],
                            summary=f"{text}: area destroyed")
    return inject


@pytest.fixture
def board() -> FakeBoard:
    b = FakeBoard()
    b.add_base("50", [{"action": "wipe_bbox", "args": {}}])  # a scenario base at 20% loss
    return b


def _match(board, tmp_path, base="50", rounds=2, llm=None, emit=None, **kw) -> Match:
    return Match(board, base, rounds, llm=llm or FakeLLM(), injector=fake_injector(board), emit=emit,
                 directory=tmp_path, **kw)


# ---------------------------------------------------------------------- stacking


def test_red_then_blue_each_round_stacked_on_the_head(board, tmp_path):
    match = _match(board, tmp_path, rounds=2)
    summary = match.run()

    assert [m.side for m in match.moves] == ["red", "blue", "red", "blue"]
    assert match.moves[0].parent_id == "50"
    for prev, move in zip(match.moves, match.moves[1:]):
        assert move.parent_id == prev.branch_id
    assert match.head == match.moves[-1].branch_id == summary["head"]
    assert summary["status"] == "done" and summary["rounds_played"] == 2


def test_each_branch_carries_its_whole_lineage(board, tmp_path):
    match = _match(board, tmp_path, rounds=1)
    match.run()
    assert [a["action"] for a in board.lineage(match.moves[-1].branch_id)] == [
        "wipe_bbox", "strike_supplier", "backup_all_affected_parts"]


# ---------------------------------------------------------------------- loss relative to the base


def test_loss_is_measured_against_the_base_not_main(board, tmp_path):
    match = _match(board, tmp_path, rounds=1)
    match.run()
    red, blue = match.moves
    assert match.base_loss == pytest.approx(0.20)
    assert (red.loss_pct, red.abs_loss_pct) == (10.0, 30.0)
    assert (blue.loss_pct, blue.abs_loss_pct) == (4.0, 24.0)


def test_match_on_main_has_zero_base(board, tmp_path):
    match = _match(board, tmp_path, base="main", rounds=1)
    match.run()
    assert match.moves[0].loss_pct == match.moves[0].abs_loss_pct == 10.0


# ---------------------------------------------------------------------- injects


def test_inject_lands_before_the_next_round_on_the_current_head(board, tmp_path):
    events: list[tuple[str, dict]] = []
    match: Match | None = None

    def emit(kind, data):
        events.append((kind, data))
        if kind == "round_done" and data["round"] == 1:
            match.inject("the Liverpool port is closed")

    match = _match(board, tmp_path, rounds=2, emit=emit)
    match.run()

    assert [m.side for m in match.moves] == ["red", "blue", "inject", "red", "blue"]
    blue1, inject, red2 = match.moves[1], match.moves[2], match.moves[3]
    assert inject.parent_id == blue1.branch_id and red2.parent_id == inject.branch_id
    assert inject.round == 1 and inject.rationale.endswith("area destroyed")
    kinds = [k for k, _ in events]
    i_done = kinds.index("round_done")
    assert kinds[i_done + 1:i_done + 3] == ["move_started", "inject"]
    assert events[i_done + 2][1]["text"] == "the Liverpool port is closed"


def test_inject_queued_before_start_lands_before_round_one(board, tmp_path):
    match = _match(board, tmp_path, rounds=1)
    match.inject("flood")
    match.run()
    assert [m.side for m in match.moves] == ["inject", "red", "blue"]
    assert match.moves[0].parent_id == "50"


def test_inject_rejected_after_the_match_ended(board, tmp_path):
    match = _match(board, tmp_path, rounds=1)
    match.run()
    with pytest.raises(ValueError):
        match.inject("too late")


# ---------------------------------------------------------------------- one decision per move


def test_one_llm_call_per_move_with_timings(board, tmp_path):
    llm = FakeLLM()
    match = _match(board, tmp_path, rounds=1, llm=llm)
    match.run()
    assert len(llm.calls) == 2
    for m in match.moves:
        assert m.llm_ms >= 0 and m.db_ms >= 0 and m.latency_ms >= m.llm_ms
        assert m.targets and not m.fallback
    assert match.moves[0].label == "Strike supplier SUP001 (Acme)"
    assert match.moves[0].rationale == "hit the top supplier"


def test_rejected_move_is_fed_back_and_retried(board, tmp_path):
    bad = json.dumps({"thought": "x", "action": "strike_supplier", "args": {"supplier_id": "BAD"}})
    llm = FakeLLM({"red": [bad]})
    match = _match(board, tmp_path, rounds=1, llm=llm)
    match.run()
    red_calls = [msgs for agent, msgs in llm.calls if agent == "red"]
    assert len(red_calls) == 2 and "BAD" in red_calls[1][-1]["content"]
    assert match.moves[0].args == {"supplier_id": "SUP001"} and not match.moves[0].fallback


def test_wrong_side_action_and_garbage_fall_back_to_default(board, tmp_path):
    wrong = json.dumps({"action": "backup_all_affected_parts", "args": {}})
    llm = FakeLLM({"red": [wrong, "no json here", wrong]})
    match = _match(board, tmp_path, rounds=1, llm=llm)
    match.run()
    red = match.moves[0]
    assert red.fallback and red.action == "strike_supplier"


def test_read_query_counts_against_the_move_budget(board, tmp_path):
    query = json.dumps({"action": "query", "args": {"cypher": "MATCH (n:Site) RETURN n"}})
    llm = FakeLLM({"red": [query]})
    match = _match(board, tmp_path, rounds=1, llm=llm)
    match.run()
    assert sum(agent == "red" for agent, _ in llm.calls) == 2 and not match.moves[0].fallback


def test_llm_failure_ends_match_with_error_and_replay_hint(board, tmp_path):
    class Down(FakeLLM):
        def chat(self, *_, **__):
            raise RuntimeError("Featherless unreachable")

    events = []
    match = _match(board, tmp_path, rounds=1, llm=Down(), emit=lambda k, d: events.append((k, d)))
    assert match.run()["status"] == "error"
    err = next(d for k, d in events if k == "error")
    assert "unreachable" in err["message"] and err["replay_available"]


# ---------------------------------------------------------------------- controls


def test_stop_before_start_ends_without_moves(board, tmp_path):
    match = _match(board, tmp_path)
    match.stop()
    assert match.run()["status"] == "stopped" and match.moves == []


def test_pause_holds_the_next_move_until_resume(board, tmp_path):
    match = _match(board, tmp_path, rounds=1)
    match.pause()
    worker = threading.Thread(target=match.run)
    worker.start()
    time.sleep(0.15)
    assert match.moves == []
    match.resume()
    worker.join(timeout=5)
    assert [m.side for m in match.moves] == ["red", "blue"]


# ---------------------------------------------------------------------- persistence + replay


def test_match_is_saved_and_listed(board, tmp_path):
    match = _match(board, tmp_path, rounds=1, save_as="demo")
    match.run()
    data = load_match("demo", tmp_path)
    assert data["base_branch"] == "50" and data["base_actions"] == [{"action": "wipe_bbox", "args": {}}]
    assert len(data["moves"]) == 2 and data["events"][-1]["type"] == "match_done"
    listed = list_matches(tmp_path)
    assert listed[0]["file"] == "demo" and listed[0]["moves"] == 2


def test_replay_rebuilds_branches_with_original_timing_and_no_llm(board, tmp_path):
    match = _match(board, tmp_path, rounds=2, save_as="demo")
    match.inject("flood")
    match.run()
    saved = load_match("demo", tmp_path)

    fresh = FakeBoard()  # a restarted server: none of the recorded branches exist; replay takes no LLM at all
    replayed: list[tuple[str, dict]] = []
    sleeps: list[float] = []
    replay(saved, fresh, lambda k, d: replayed.append((k, d)), speed=2.0, sleep=sleeps.append)

    assert [k for k, _ in replayed] == [e["type"] for e in saved["events"]]
    moves = [d if k == "move" else d["move"] for k, d in replayed if k in ("move", "inject")]
    assert [m["side"] for m in moves] == ["inject", "red", "blue", "red", "blue"]
    base = next(d for k, d in replayed if k == "match_started")["base_branch"]
    assert base != "50" and fresh.lineage(base) == [{"action": "wipe_bbox", "args": {}}]
    assert moves[0]["parent_id"] == base
    for prev, move in zip(moves, moves[1:]):
        assert move["parent_id"] == prev["branch_id"]
    assert fresh.loss(moves[-1]["branch_id"]) == pytest.approx(board.loss(match.head))
    assert all(d["replay"] for _, d in replayed)
    assert max(sleeps, default=0) <= saved["events"][-1]["t"] / 2.0 + 0.05  # recorded clock, scaled


def test_replay_can_be_stopped(board, tmp_path):
    match = _match(board, tmp_path, rounds=1, save_as="demo")
    match.run()
    stop = threading.Event()
    stop.set()
    out = []
    assert replay(load_match("demo", tmp_path), FakeBoard(), lambda k, d: out.append(k), stop=stop,
                  sleep=lambda _: None)["status"] == "stopped"
    assert out == ["match_done"]


def test_match_path_rejects_paths(tmp_path):
    assert match_path("demo", tmp_path).name == "demo.json"
    assert match_path("demo.json", tmp_path).name == "demo.json"
    for bad in ("../etc/passwd", "a/b", "", "x" * 80):
        with pytest.raises(ValueError):
            match_path(bad, tmp_path)


def test_describe_action_in_plain_words():
    assert describe_action("strike_plant", {"gppd_idnr": "W1"}, {"names": {"W1": "Big Plant"}}) == \
        "Strike power plant W1 (Big Plant)"
    assert describe_action("restore_power", {"site_id": "SITE04"}) == "Restore power to SITE04"
    assert describe_action("cut_route", {"supplier": "SUP2"}) == "Cut logistics routes of SUP2"
    assert describe_action("strike_supplier", {}) == "Strike supplier"


# ---------------------------------------------------------------------- no loops: red varies its moves


def test_red_may_not_repeat_its_last_kind_of_move(board, tmp_path):
    match = _match(board, tmp_path, rounds=3)
    match.run()
    reds = [m.action for m in match.moves if m.side == "red"]
    assert reds == ["strike_supplier", "strike_plant", "strike_supplier"]
    assert all(a != b for a, b in zip(reds, reds[1:]))


def test_insisting_on_a_banned_move_falls_back_to_an_allowed_one(board, tmp_path):
    same = json.dumps({"action": "strike_supplier", "args": {"supplier_id": "SUP001"}})
    llm = FakeLLM({"red": [same, same, same, same]})  # round 2: three refusals, then the fallback
    match = _match(board, tmp_path, rounds=2, llm=llm)
    match.run()
    red2 = [m for m in match.moves if m.side == "red"][1]
    assert red2.fallback and red2.action == "strike_plant"
    refusal = [msgs for agent, msgs in llm.calls if agent == "red"][2][-1]["content"]
    assert "not a red action" in refusal


def test_fallback_tries_alternates_when_the_default_is_refused(board, tmp_path):
    class Refusing(FakeBoard):
        def stack(self, side, label, parent, actions):
            if actions[0]["action"] == "strike_supplier":
                raise MoveRejected("supplier is hardened")
            return super().stack(side, label, parent, actions)

    b = Refusing()
    match = Match(b, "main", 1, llm=FakeLLM({"red": ["x", "y", "z"]}), injector=fake_injector(b), directory=tmp_path)
    assert match.run()["status"] == "done"
    assert match.moves[0].action == "strike_plant" and match.moves[0].fallback


def test_prompt_keeps_every_candidate_kind_without_truncating_json():
    from agents.match_prompts import task_prompt

    candidates = [{"action": kind, "args": {"id": str(i)}, "target": "long target " * 40,
                   "est_gain_pct": 20 - i}
                  for kind in ("close_port", "block_chokepoint", "facility_outage", "export_controls")
                  for i in range(4)]
    prompt = task_prompt("red", 1, 4, [], {"abs_loss_pct": 0, "loss_pct": 0},
                         {"deep_candidates": candidates, "alternates": candidates, "names": {}})
    encoded = prompt.split("OPTIONS (current state):\n", 1)[1].split("\n\nReply", 1)[0]
    shown = json.loads(encoded)
    assert len(shown["deep_candidates"]) == 8
    assert {c["action"] for c in shown["deep_candidates"]} == {c["action"] for c in candidates}
    assert "alternates" not in shown


def test_cli_module_retries_board_rejections(board, tmp_path):
    import runpy
    from agents.config import ROOT

    cli = runpy.run_path(str(ROOT / "agents" / "match.py"), run_name="match_cli_test")
    bad = json.dumps({"action": "strike_supplier", "args": {"supplier_id": "BAD"}})
    match = cli["Match"](board, "main", 1, llm=FakeLLM({"red": [bad]}), directory=tmp_path)
    assert match.run()["status"] == "done"
    assert len(match.moves) == 2
    assert match.moves[0].args["supplier_id"] != "BAD"


def test_cooldown_filters_both_recent_kinds_and_fallbacks():
    from agents.match import _without

    moves = [{"action": name, "args": {}} for name in ("close_port", "block_chokepoint", "facility_outage")]
    options = _without({"deep_candidates": moves, "fallback": moves[0], "alternates": moves[1:]},
                       ["close_port", "block_chokepoint"])
    assert options["deep_candidates"] == [moves[2]]
    assert options["fallback"] == moves[2] and not options["alternates"]


def test_strategic_wait_does_not_call_model_when_it_is_the_only_legal_move(board, tmp_path, monkeypatch):
    class BudgetBoard:
        def __init__(self, raw, rounds, seed):
            self.raw = raw
            self.last_options = {}

        def __getattr__(self, name):
            return getattr(self.raw, name)

        def initialize(self, base):
            return self.raw.stack("blue", "init", base, [{"action": "game_init", "args": {}}])

        def details(self, head):
            return {"budget_remaining": 1, "budget_total": 14, "pending": [], "completed": [], "missions": []}

        def missions(self, head):
            return []

        def tick(self, head, rnd):
            actions = [{"action": "game_tick", "args": {"round": rnd}}]
            return self.raw.stack("inject", "clock", head, actions), actions, "clock"

        def options(self, side, head):
            options = self.raw.options(side, head)
            if side == "blue":
                options = {"deep_candidates": [{"action": "wait", "args": {}}]}
            self.last_options = options
            return options

        def play(self, side, label, head, step):
            return self.raw.stack(side, label, head, [step]), [step]

    monkeypatch.setattr("agents.strategic_board.StrategicBoard", BudgetBoard)
    model = FakeLLM()
    match = Match(board, rounds=1, strategic=True, llm=model, directory=tmp_path)
    assert match.run()["status"] == "done"
    assert [side for side, _ in model.calls] == ["red"]
    blue = [m for m in match.moves if m.side == "blue"]
    assert len(blue) == 2 and all(m.action == "wait" and not m.fallback for m in blue)


def test_stopped_half_round_has_correct_average_loss(board, tmp_path):
    match = None

    def emit(kind, data):
        if kind == "move" and data["side"] == "red":
            match.stop()

    match = _match(board, tmp_path, rounds=2, emit=emit)
    result = match.run()
    assert result["status"] == "stopped"
    assert result["cumulative_loss"] == 5
    assert result["average_loss_pct"] == 10
    assert not result["objective_met"]


def test_provider_response_failure_uses_marked_legal_fallback(board, tmp_path):
    from agents.llm import LLMError

    class BrokenResponse(FakeLLM):
        def chat(self, *args, **kwargs):
            raise LLMError("malformed provider response")

    match = _match(board, tmp_path, rounds=1, llm=BrokenResponse())
    assert match.run()["status"] == "done"
    assert all(m.fallback for m in match.moves)
