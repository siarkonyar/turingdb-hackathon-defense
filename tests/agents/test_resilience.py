"""Offline checks of the Dover resilience engine, agent and runner. No server, no network, no real model."""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache

import pytest

from agents.llm import LLMUnavailable
from agents.resilience.agent import decide
from agents.resilience.availability import Conditions, evaluate
from agents.resilience.candidates import prepare_candidates, route_checks
from agents.resilience.cargo import limits
from agents.resilience.exercises import EXERCISES, UnsupportedExercise, get_exercise, targets
from agents.resilience.lab import BranchRecord, decode, encode, plan_from_spec, plan_spec
from agents.resilience.network import from_corridor
from agents.resilience.plans import Action, Plan, PlanRejected, prepare
from agents.resilience.simulate import simulate

IDS = sorted(EXERCISES)


@lru_cache(maxsize=1)
def net():
    return from_corridor()


@lru_cache(maxsize=None)
def cands(sid: str):
    return prepare_candidates(net(), get_exercise(sid))


def best(sid: str):
    return cands(sid).candidates[0]


class ScriptedModel:
    """Deterministic provider double: returns scripted JSON actions and checks every call is bounded."""

    model = "scripted-double"

    def __init__(self, replies: list[dict]) -> None:
        self.replies = [json.dumps(r) for r in replies]
        self.calls = 0

    def chat(self, messages, **kw):
        assert kw.get("bounded") is True and kw.get("max_tokens")
        self.calls += 1
        return self.replies.pop(0) if self.replies else json.dumps({"thought": "stop", "action": "finish", "args": {}})


class FailingModel:
    model = "unreachable-double"

    def chat(self, messages, **kw):
        raise LLMUnavailable("cannot reach provider")


def script(choice: str) -> list[dict]:
    return [
        {"thought": "see options", "action": "list_candidates", "args": {}},
        {"thought": "measure", "action": "compare_plans", "args": {}},
        {"thought": "best essential", "action": "execute_plan", "args": {"candidate_id": choice, "rationale": "r"}},
        {"thought": "done", "action": "finish", "args": {"choice": choice}},
    ]


def one(kind: str, target: str, option: str) -> Plan:
    return Plan("probe", "probe", "", (Action(kind, target, f"recovery:{target}:{option}"),))  # type: ignore[arg-type]


# ------------------------------------------------------------------ data and exercise scope


def test_network_matches_the_dataset_contract():
    n = net()
    assert len(n.consignments) == 20 and len(n.demands) == 260
    assert sum(c.tonnes for c in n.consignments) == pytest.approx(1084.2)
    assert set(n.route_ends) == {f"route:{r}" for r in ("dover_calais", "dover_dunkirk", "western_channel", "tunnel",
                                                          "london_paris_air", "kent_beauvais_air")}


def test_only_the_three_exercises_are_supported():
    assert IDS == ["scenario:kent_power", "scenario:london_loss", "scenario:strait_closure"]
    with pytest.raises(UnsupportedExercise):
        get_exercise("scenario:calais_port")
    assert targets(net(), get_exercise("scenario:strait_closure")) == ("chokepoint:dover",)
    assert len(targets(net(), get_exercise("scenario:kent_power"))) == 10


def test_baseline_without_event_serves_everything():
    n = net()
    avail = evaluate(n, Conditions(frozenset(), inflow={c.receiver: 1.0 for c in n.consignments}))
    assert min(avail.values()) == pytest.approx(1.0)


def test_missing_material_share_stays_in_the_denominator():
    d = cands("scenario:strait_closure").disruption
    assert d.avail_min["local:paris:food:distribution"] == pytest.approx(0.4)  # 60% import lost, 40% local kept
    assert d.avail_min["mission:paris:military_hospital"] == pytest.approx(0.4)
    assert d.metrics.essential_fulfilment == pytest.approx(0.4)


# ------------------------------------------------------------------ scenario rules


def test_strait_closure_keeps_independent_crossings_and_closes_both_strait_routes():
    o = cands("scenario:strait_closure").disruption
    assert o.avail_min["route:dover_calais"] == 0 and o.avail_min["route:dover_dunkirk"] == 0
    for r in ("tunnel", "western_channel", "london_paris_air", "kent_beauvais_air"):
        assert o.avail_min[f"route:{r}"] == 1.0
    moved = best("scenario:strait_closure").outcome.consumption.route_tonnes
    assert "route:dover_dunkirk" not in moved and "route:dover_calais" not in moved


def test_air_cannot_replace_unlimited_freight():
    o = best("scenario:strait_closure").outcome
    days = get_exercise("scenario:strait_closure").days
    for air in ("route:london_paris_air", "route:kent_beauvais_air"):
        assert o.consumption.route_tonnes.get(air, 0.0) <= 64 * days + 1e-6
    assert o.metrics.cargo_unmet_t > 0  # independent capacity (568 t/day) is below 1,084.2 t/day


def test_kent_outage_rules_out_alternatives_by_their_own_dependencies():
    checks = {c.route: c for c in route_checks(net(), get_exercise("scenario:kent_power"), "route:dover_calais")}
    assert not checks["route:tunnel"].available and not checks["route:kent_beauvais_air"].available
    assert any("Folkestone" in b for b in checks["route:tunnel"].blockers)
    assert checks["route:western_channel"].available and checks["route:london_paris_air"].available
    out = simulate(net(), get_exercise("scenario:kent_power"), one("reroute", "route:dover_calais", "reroute_tunnel"))
    assert out.consumption.route_tonnes.get("route:tunnel", 0.0) == 0.0


def test_regional_destruction_is_never_restored_or_delivered_to():
    ex = get_exercise("scenario:london_loss")
    lost = frozenset(targets(net(), ex))
    with pytest.raises(PlanRejected, match="destroyed"):
        prepare(net(), ex, one("mobile_power", "local:london:medical:service", "mobile_power"), lost)
    with pytest.raises(PlanRejected, match="disabled|destroyed"):
        prepare(net(), ex, one("release_stock", "local:london:medical:service", "release_stock"), lost)
    o = best("scenario:london_loss").outcome
    assert all(t.receiver not in lost and t.provider not in lost for t in o.prepared.transfers)
    assert all(o.avail_end.get(e, 0.0) == 0.0 for e in lost)
    assert o.demand_fulfilment["demand:london:medical"] > 0  # served only through the relocation
    assert cands("scenario:london_loss").disruption.demand_fulfilment["demand:london:medical"] == 0.0


# ------------------------------------------------------------------ conservation


@pytest.mark.parametrize("sid", IDS)
def test_shared_capacity_is_never_exceeded(sid):
    o = best(sid).outcome
    used: dict[tuple[int, str], float] = defaultdict(float)
    direction = {c.eid: c.direction for c in net().consignments}
    for s in o.shipments:
        for key, cap in limits(net(), s.route, direction[s.consignment]):
            used[(s.day, key)] += s.tonnes
            assert used[(s.day, key)] <= cap + 1e-6, (s.day, key)
    from agents.resilience.simulate import _Run

    for day in _Run(net(), get_exercise(sid), best(sid).plan).days:  # four aircraft x one rotation per pool per day
        assert all(n <= 4 for n in day.sorties.values()), day.sorties
    tonnes = {c.eid: c.tonnes for c in net().consignments}
    per_day: dict[tuple[int, str], float] = defaultdict(float)
    for s in o.shipments:
        per_day[(s.day, s.consignment)] += s.tonnes
    assert all(v <= tonnes[c] + 1e-6 for (_, c), v in per_day.items())  # never more than it carries


@pytest.mark.parametrize("sid", IDS)
def test_stock_generators_and_spare_are_conserved(sid):
    o = best(sid).outcome
    p = o.prepared
    stocked = {r.reserve: r.stock_t for r in p.releases}
    for reserve, used in o.consumption.stock_released_by_reserve.items():
        assert used <= stocked[reserve] + 1e-6
    per_stock: dict[str, int] = defaultdict(int)
    for f in p.feeds:
        per_stock[f.stock] += f.generators
        assert f.load_mw <= f.provided_mw
    assert all(n <= 3 for n in per_stock.values())
    spare: dict[str, float] = defaultdict(float)
    for t in p.transfers:
        spare[t.provider] += t.tonnes_day
    assert all(v <= 20 + 1e-6 for v in spare.values())
    fed = [x for f in p.feeds for x in f.loads]
    assert len(fed) == len(set(fed))  # no load counted on two generators


def test_stock_depletes_at_the_gap_rate():
    assert best("scenario:strait_closure").outcome.consumption.stock_released_t > 0
    out = simulate(net(), get_exercise("scenario:strait_closure"),
                   one("release_stock", "local:paris:food:service", "release_stock"))
    assert out.consumption.stock_released_by_reserve["reserve:paris:food"] == pytest.approx(0.6 * 12 * 2)  # 48 h gap
    # the 48 h release duration ends the draw-down: over 72 h the gap would have taken 21.6 t
    assert out.consumption.stock_released_t < 0.6 * 12 * 3


def test_generator_pool_is_finite():
    ex = get_exercise("scenario:kent_power")
    actions = tuple(Action("mobile_power", f, f"recovery:{f}:mobile_power")
                    for f in ("infra:dover:water_works", "infra:dover:telecom_exchange", "infra:dover:fuel_depot",
                              "local:dover:medical:service"))
    with pytest.raises(PlanRejected, match="no mobile generator left"):
        prepare(net(), ex, Plan("g", "g", "", actions), frozenset(targets(net(), ex)))


def test_cold_chain_stock_needs_powered_storage():
    cold = Plan("c", "c", "", (Action("mobile_power", "local:dover:cold:service",
                                      "recovery:local:dover:cold:service:mobile_power"),
                               Action("release_stock", "local:dover:cold:service",
                                      "recovery:local:dover:cold:service:release_stock")))
    assert simulate(net(), get_exercise("scenario:kent_power"), cold).consumption.stock_released_t == 0.0


@pytest.mark.parametrize("sid", IDS)
def test_recovery_improves_and_is_deterministic(sid):
    b = best(sid)
    assert b.outcome.metrics.essential_fulfilment > cands(sid).disruption.metrics.essential_fulfilment
    assert simulate(net(), get_exercise(sid), b.plan).metrics == b.outcome.metrics


def test_plan_spec_round_trip_replays_identically():
    b = best("scenario:kent_power")
    assert plan_from_spec(decode(encode({"plan": plan_spec(b.plan)}))["plan"]) == b.plan


# ------------------------------------------------------------------ agent with provider doubles


@pytest.mark.parametrize("sid", IDS)
def test_agent_executes_an_evaluated_candidate(sid):
    cs = cands(sid)
    choice = cs.candidates[-1].plan.plan_id  # not the top: the agent's own validated choice is honoured
    executed: list[str] = []
    model = ScriptedModel(script(choice))
    d = decide(net(), get_exercise(sid), cs, lambda pid: executed.append(pid) or {"branch": "9"}, model)
    assert (d.mode, d.plan_id, executed, d.calls, d.model) == ("agent", choice, [choice], 4, "scripted-double")


def test_agent_cannot_execute_without_evaluating():
    cs = cands("scenario:strait_closure")
    choice = cs.candidates[0].plan.plan_id
    replies = [{"thought": "rush", "action": "execute_plan", "args": {"candidate_id": choice}}]
    d = decide(net(), get_exercise("scenario:strait_closure"), cs, lambda pid: {"branch": "1"}, ScriptedModel(replies))
    assert d.mode == "fallback" and d.plan_id == choice and "without executing" in (d.reason or "")


def test_provider_failure_uses_labelled_prepared_plan():
    cs = cands("scenario:london_loss")
    ex = get_exercise("scenario:london_loss")
    d = decide(net(), ex, cs, lambda pid: {"branch": "2"}, FailingModel())
    assert d.mode == "fallback" and d.plan_id == cs.candidates[0].plan.plan_id
    assert d.reason == "model provider unavailable (LLMUnavailable)"
    d = decide(net(), ex, cs, lambda pid: {"branch": "2"}, None, unavailable_reason="no key")
    assert d.mode == "fallback" and d.reason == "no key" and d.calls == 0


def test_agent_steps_are_bounded():
    cs = cands("scenario:kent_power")
    model = ScriptedModel([{"thought": "again", "action": "list_candidates", "args": {}}] * 20)
    d = decide(net(), get_exercise("scenario:kent_power"), cs, lambda pid: {"branch": "3"}, model)
    assert model.calls == 6 and d.mode == "fallback"


# ------------------------------------------------------------------ runner end to end, with a fake lab


class FakeLab:
    """Branch writes recorded in memory; verification re-measures the stored plan, like the live lab."""

    def __init__(self) -> None:
        self.branches: dict[str, dict] = {}

    def network(self):
        return net()

    def disrupt(self, ex, outcome, hits):
        bid = str(len(self.branches))
        self.branches[bid] = {"role": "disruption", "targets": sorted(outcome.initial)}
        return BranchRecord(bid, "disruption", ex.scenario_id, None, "main", True)

    def recover(self, ex, plan, outcome, comparison, parent):
        bid = str(len(self.branches))
        self.branches[bid] = {"role": "recovery", "targets": sorted(outcome.initial), "plan": plan_spec(plan)}
        ok = simulate(net(), ex, plan_from_spec(self.branches[bid]["plan"])).metrics == outcome.metrics
        return BranchRecord(bid, "recovery", ex.scenario_id, plan.plan_id, parent, ok)


@pytest.mark.parametrize("sid", IDS)
def test_runner_streams_disruption_then_recovery(sid):
    from api.resilience_models import DisruptionView, RecoveryView
    from api.resilience_routes import ExerciseRunner

    lab = FakeLab()
    choice = cands(sid).candidates[0].plan.plan_id
    runner = ExerciseRunner(lab, model_factory=lambda: (ScriptedModel(script(choice)), None))
    runner._cands[sid] = cands(sid)
    events: list[tuple[str, dict]] = []
    payload = runner.run(sid, lambda kind, data: events.append((kind, data)))
    kinds = [k for k, _ in events]
    assert kinds[0] == "phase" and kinds.index("disruption") < kinds.index("agent_step") < kinds.index("recovery")
    dis = DisruptionView.model_validate(dict(events)["disruption"])
    rec = RecoveryView.model_validate(payload)
    assert dis.cascade.origin_kind == "event" and dis.cascade.measure == "service_loss"
    assert len(dis.cascade.origins) == len(targets(net(), get_exercise(sid)))
    assert [s.degree for s in dis.cascade.stages] == list(range(1, dis.cascade.max_degree + 1))
    assert rec.decision.mode == "agent" and rec.branch.verified and rec.branch.parent == dis.branch.branch
    assert lab.branches[rec.branch.branch]["targets"] == lab.branches[dis.branch.branch]["targets"]  # replayed
    assert rec.after.essential_fulfilment > rec.before.essential_fulfilment
    assert rec.groups and all(g.ready_h >= 0 for g in rec.groups)


# ------------------------------------------------------------------ free text and step grouping


@pytest.mark.parametrize("text, expected", [
    ("Close the Dover Strait to shipping for 72 hours", "scenario:strait_closure"),
    ("what if ferries stop crossing the channel?", "scenario:strait_closure"),
    ("Kent has a blackout", "scenario:kent_power"),
    ("the grid goes down across the region", "scenario:kent_power"),
    ("Croydon and London are destroyed", "scenario:london_loss"),
])
def test_free_text_maps_to_an_exercise(text, expected):
    from agents.resilience.exercises import match_question

    assert match_question(text).scenario_id == expected


@pytest.mark.parametrize("text", ["hello", "what is the weather in Lyon?", "London grid outage"])
def test_free_text_without_a_clear_event_gets_no_run(text):
    from agents.resilience.exercises import match_question

    assert match_question(text) is None  # no cue, or a tie between two events


@pytest.mark.parametrize("sid", IDS)
def test_every_map_link_belongs_to_a_recovery_step(sid):
    from agents.resilience.explain import links
    from agents.resilience.plans import group_actions

    b = best(sid)
    keys = set(group_actions(b.plan))
    assert {link.group for link in links(net(), b.outcome)} <= keys
