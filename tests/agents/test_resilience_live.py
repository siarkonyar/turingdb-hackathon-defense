"""Live checks on the dedicated in-memory Dover server (port 6667) with a deterministic provider double.

Run serially: DOVER_LIVE=1 .venv/bin/python -m pytest tests/agents/test_resilience_live.py -q
Every branch created here is discarded at the end; main must be unchanged throughout.
"""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("DOVER_LIVE") != "1", reason="set DOVER_LIVE=1 for port 6667")

IDS = ("scenario:strait_closure", "scenario:kent_power", "scenario:london_loss")


class ScriptedModel:
    model = "scripted-double"

    def __init__(self, choice: str) -> None:
        self.replies = [json.dumps(r) for r in (
            {"thought": "list", "action": "list_candidates", "args": {}},
            {"thought": "compare", "action": "compare_plans", "args": {}},
            {"thought": "execute", "action": "execute_plan", "args": {"candidate_id": choice, "rationale": "best"}},
            {"thought": "done", "action": "finish", "args": {"choice": choice}},
        )]

    def chat(self, messages, **kw):
        assert kw.get("bounded") is True
        return self.replies.pop(0)


@pytest.fixture(scope="module")
def lab():
    from agents.resilience.lab import ResilienceLab
    from api.backends.turing import TuringBackend
    from datasets.dover.build import HOST

    lab = ResilienceLab(TuringBackend(HOST, "dover"))
    before = {str(c) for c in lab._session("main").q("CHANGE LIST").iloc[:, 0]}
    yield lab
    after = {str(c) for c in lab._session("main").q("CHANGE LIST").iloc[:, 0]}
    for change in sorted(after - before, key=int):
        lab.discard(change)


def test_live_network_equals_the_generator(lab):
    from agents.resilience.network import from_corridor

    live, offline = lab.network(), from_corridor()
    assert set(live.entities) == set(offline.entities)
    assert dict(live.depends) == dict(offline.depends) and live.order == offline.order
    assert live.consignments == offline.consignments and live.demands == offline.demands


@pytest.mark.parametrize("sid", IDS)
def test_live_suggestion_to_impact_to_recovery(lab, sid):
    from agents.resilience.exercises import get_exercise
    from api.resilience_models import DisruptionView, RecoveryView
    from api.resilience_routes import ExerciseRunner

    head = lab.main_head()
    runner = ExerciseRunner(lab)
    choice = runner.candidates(get_exercise(sid)).candidates[0].plan.plan_id
    runner.model_factory = lambda: (ScriptedModel(choice), None)
    events: list[tuple[str, dict]] = []
    payload = runner.run(sid, lambda k, d: events.append((k, d)))
    dis = DisruptionView.model_validate(dict(events)["disruption"])
    rec = RecoveryView.model_validate(payload)
    assert dis.branch.verified and rec.branch.verified and rec.decision.mode == "agent"
    assert dis.cascade.reach.ms is not None and dis.cascade.reach.reached >= dis.cascade.total_affected
    disruption, recovery = lab.read_state(dis.branch.branch), lab.read_state(rec.branch.branch)
    assert disruption.targets_down == recovery.targets_down  # the recovery branch replayed the disruption
    assert not disruption.active_options and len(recovery.active_options) == len(recovery.spec["plan"]["actions"])
    assert recovery.allocations > 0 and recovery.states
    assert lab.main_head() == head
    assert "ResilienceBranch" not in lab._session("main").labels


def test_live_replay_rebuilds_an_identical_branch(lab):
    from agents.resilience.candidates import prepare_candidates
    from agents.resilience.exercises import get_exercise
    from agents.resilience.explain import cascade, compare

    head = lab.main_head()
    ex = get_exercise("scenario:kent_power")
    cands = prepare_candidates(lab.network(), ex)
    best = cands.candidates[0]
    first = lab.disrupt(ex, cands.disruption, [h for layer in cascade(lab.network(), cands.disruption) for h in layer])
    cmp = compare(lab.network(), cands.disruption, best.outcome)
    original = lab.recover(ex, best.plan, best.outcome, cmp, first.branch)
    replayed = lab.replay(original.branch, best.outcome, comparison=cmp)
    a, b = lab.read_state(original.branch), lab.read_state(replayed.branch)
    assert replayed.verified and replayed.branch != original.branch
    assert (a.targets_down, a.active_options, a.allocations, a.states) == \
           (b.targets_down, b.active_options, b.allocations, b.states)
    assert a.spec["plan"] == b.spec["plan"] and a.spec["event"] == b.spec["event"]
    assert lab.main_head() == head


def test_live_routes_mount_only_for_dover(monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import create_app

    monkeypatch.setenv("OPSMAP_BACKEND", "turingdb")
    monkeypatch.setenv("TURINGDB_GRAPH", "dover")
    monkeypatch.setenv("TURINGDB_HOST", "http://localhost:6667")
    with TestClient(create_app()) as client:
        body = client.get("/resilience/exercises").json()
        assert [e["scenario_id"] for e in body["exercises"]] == list(IDS)
        assert client.post("/resilience/run", json={"scenario_id": "scenario:calais_port"}).status_code == 422
