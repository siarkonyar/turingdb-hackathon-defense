"""Scarcity, lead times, expiry and shared capacity on small offline exercise states."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
import pandas as pd

from agents import game_rules as G
from agents import deep_impact as D
from tests.agents.test_deep_impact import static, state  # reuse the hand-built network fixtures


def test_game_payload_survives_cypher_quote_replacement():
    import base64
    import json

    class Session:
        labels = set()

        def q(self, query):
            if query.startswith("CREATE"):
                self.payload = query.split("payload: '", 1)[1].split("'", 1)[0]
            return pd.DataFrame({"payload": [self.payload]}) if query.startswith("MATCH") else pd.DataFrame()

        def refresh_schema(self):
            self.labels = {"GameState"}

    session = Session()
    value = {"round": 1, "completed": ['A "quoted" name, a backslash \\ and Türkiye']}
    G._write(session, value)
    assert json.loads(base64.b64decode(session.payload)) == value
    assert G.read_game(session) == value


@pytest.fixture
def game(monkeypatch):
    data = {"round": 0, "rounds": 6, "budget": G.BUDGET, "pending": [], "stocks": [],
            "completed": [], "seed": 7, "event_until": -1}
    monkeypatch.setattr(G, "read_game", lambda s: deepcopy(data))
    monkeypatch.setattr(G, "_write", lambda s, value: (data.clear(), data.update(deepcopy(value))))
    return data


def test_order_spends_once_and_only_executes_when_due(game, monkeypatch):
    applied = []
    monkeypatch.setattr("agents.actions.apply_action", lambda lab, s, action, args: applied.append((action, args)))
    G.game_order(None, None, action="replace_facility", args={"facility_id": "F1"})
    assert game["budget"] == 9 and not applied
    with pytest.raises(ValueError, match="already pending"):
        G.game_order(None, None, action="replace_facility", args={"facility_id": "F1"})
    G.game_tick(None, None, round=1)
    assert not applied
    G.game_tick(None, None, round=2)
    assert applied == [("replace_facility", {"facility_id": "F1"})]
    assert not game["pending"] and game["budget"] == 9


def test_budget_cannot_be_bypassed_and_wait_is_free(game):
    game["budget"] = 1
    with pytest.raises(ValueError, match="only 1 credits"):
        G.game_order(None, None, action="harden", args={"port_id": "P"})
    assert game["budget"] == 1
    G.game_order(None, None, action="wait", args={})
    assert game["budget"] == 1


def test_stock_expires_and_seeded_event_has_finite_duration(game, monkeypatch):
    writes = []
    monkeypatch.setattr("agents.actions.apply_action", lambda *args: None)
    monkeypatch.setattr("agents.deep_actions._item", lambda *args: 42)
    monkeypatch.setattr("agents.deep_actions._set", lambda *args: writes.append(args))
    G.game_order(None, None, action="stockpile", args={"item_id": "M"})
    G.game_tick(None, None, round=1)
    assert not writes
    G.game_tick(None, None, round=2)
    assert not writes  # preparation stock covers combat rounds 1 and 2
    G.game_tick(None, None, round=3)
    assert writes == [(None, 42, "stockpile", "false")]
    assert not game["stocks"]
    with pytest.raises(ValueError, match="one round"):
        G.game_tick(None, None, round=5)
    G.game_tick(None, None, round=4)
    assert game["event_until"] == 6
    G.game_tick(None, None, round=5)
    assert game["event_until"] > game["round"]
    G.game_tick(None, None, round=6)
    assert game["event_until"] == game["round"]


def test_pending_failure_keeps_cost_and_does_not_stop_match(game, monkeypatch):
    def fail(*args):
        raise ValueError("replacement capacity no longer available")
    monkeypatch.setattr("agents.actions.apply_action", fail)
    G.game_order(None, None, action="second_source", args={"item_id": "C"})
    G.game_tick(None, None, round=1)
    G.game_tick(None, None, round=2)
    assert game["budget"] == 11 and not game["pending"]
    assert game["completed"][0].startswith("Failed")


def test_capacity_shares_congestion_with_existing_exporters(static, state):
    static = replace(static, original_makers=state.produced_at)
    strategic = replace(state, capacity_limited=True,
                        ships_via={"F0": ("USA1",), "F1": ("USA1",), "F2": ("USA1",), "F3": ("USA1",)})
    # NY has two exporter slots. Four exporters reduce everyone's throughput, including its old prime.
    result = D.evaluate(static, strategic)
    assert result.facility_ok["F0"] == pytest.approx(0.5)
    assert result.facility_ok["F1"] == pytest.approx(0.4)
    assert result.loss >= 0.5


def test_replacement_capacity_is_consumed_and_hardening_is_partial(static, state):
    static = replace(static, original_makers=state.produced_at)
    strategic = replace(state, capacity_limited=True,
                        produced_at={**state.produced_at, "C": state.produced_at["C"] + (("F3", 50),),
                                     "M": (("F3", 50),), "S": (("F3", 50),)})
    assert D.evaluate(static, strategic).facility_ok["F3"] == pytest.approx(0.5 / 0.6)
    hardened = D.with_changes(replace(state, capacity_limited=True), protected={"F0", "USA1"}, closed={"F0", "USA1"})
    assert D.facility_ok(static, hardened, "F0") == pytest.approx(0.5 * 0.7)
    assert D.port_factor(static, hardened, "USA1") == 0.7
    no_power = replace(hardened, powered=frozenset(), closed=hardened.closed | {"F1"},
                       protected=hardened.protected | {"F1"})
    assert D.facility_ok(static, no_power, "F1") == 0


def test_proactive_options_need_measured_benefit_and_time_to_finish(static, state, monkeypatch):
    from agents.strategic_board import StrategicBoard

    static = replace(static, country_share={}, original_makers=state.produced_at)
    state = replace(state, capacity_limited=True)

    class Board:
        lab = None

        def deep(self, head):
            return state, D.evaluate(static, state)

    monkeypatch.setattr("agents.strategic_board.deep_static", lambda lab: static)
    board = StrategicBoard(Board(), 4)
    game = {"round": 0, "budget": 14, "pending": []}
    board.game = lambda head: game
    options = board._candidates("blue", "main")
    assert any(c["action"] == "stockpile" and c["args"]["item_id"] == "CMP1" for c in options)
    assert not any(c["action"] == "stockpile" and c["args"]["item_id"] == "MAT1" for c in options)
    game["round"] = 4
    assert all(c["lead_rounds"] == 0 for c in board._candidates("blue", "main"))
    assert all(c["action"] not in ("close_port", "block_chokepoint")
               for c in board._candidates("red", "main", ["close_port", "block_chokepoint"]))


def test_blue_planning_uses_next_round_and_red_cooldown():
    from types import SimpleNamespace
    from agents.strategic_board import StrategicBoard

    class Board:
        def __init__(self):
            self.rounds = {"head": 1}
            self.deleted = []
            self._deep_cache = {}
            self.lab = SimpleNamespace(discard=lambda branch: self.deleted.append(branch))

        def stack(self, side, label, parent, actions):
            branch = str(len(self.rounds))
            self.rounds[branch] = actions[0]["args"]["round"] if actions[0]["action"] == "game_tick" else self.rounds[parent]
            return branch

        def loss(self, branch):
            return 0.2

    raw = Board()
    board = StrategicBoard(raw, 4)
    board.game = lambda branch: {"round": raw.rounds[branch]}
    board.missions = lambda branch: []
    board.banned = "close_port"
    observed = []

    def candidates(side, branch, banned):
        observed.append((side, raw.rounds[branch], banned))
        return [{"action": "facility_outage", "args": {"facility_id": "F1"}}]

    board._candidates = candidates
    preview = board._preview("blue", "head", {"action": "harden", "args": {"port_id": "P"}})
    assert observed == [("red", 2, "close_port")]
    assert preview["horizon_round"] == 3
    assert len(raw.deleted) == preview["branches_evaluated"]


def test_strategic_shortlist_includes_high_share_programme_makers(static, state):
    from agents.deep_actions import red_candidates

    extra = {**static.facilities["F0"], "facility_id": "FAC4", "name": "Second assembly plant"}
    static = replace(static, facilities={**static.facilities, "F4": extra})
    state = replace(state, facilities=state.facilities | {"F4"}, capacity_limited=True,
                    produced_at={**state.produced_at, "P": (("F0", 80), ("F4", 20))})
    static = replace(static, original_makers=state.produced_at)
    candidates = red_candidates(static, state, 2)
    major = next(c for c in candidates if c["action"] == "facility_outage" and c["args"]["facility_id"] == "FAC0")
    assert major["est_gain_pct"] == 80
    assert not major["single_point_of_failure"]
