"""Offline priority selection boundaries and integration: no credentials or network required."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.blue_selection import BlueSelector
from agents.jev import FeatherlessClassifier, JevSettings
from agents.match import Match


CANDIDATES = [
    {"action": "backup_all_affected_parts", "args": {"only_critical": True}},
    {"action": "add_backup_supplier", "args": {"part_id": "B1"}},
    {"action": "restore_power", "args": {"facility_id": "SITE1"}},
]


class Model:
    model = "fake"

    def __init__(self, offered=False):
        self.calls = []
        self.offered = offered

    def chat(self, messages, agent="agent", **kwargs):
        self.calls.append(agent)
        if agent == "blue_candidates":
            return json.dumps({"action": "propose", "args": {
                "candidates": ["c1", "c2", "c3"] if self.offered else CANDIDATES}})
        if agent == "blue_explanation":
            return json.dumps({"action": "finish", "args": {"explanation": "Protected critical parts."}})
        return json.dumps({"thought": "existing decision", "action": "backup_all_affected_parts", "args": {}})


class Classifier:
    def __init__(self, choice="c1"):
        self.choice = choice
        self.calls = []

    def choose(self, state, candidates):
        self.calls.append((state, candidates))
        return {"selected_id": self.choice, "confidence": 0.7,
                "probabilities": {c["id"]: 0.7 if c["id"] == self.choice else 0.15 for c in candidates},
                "request_ms": 1}


def valid(step):
    return {"loss_pct": 15, "critical_parts_restored": ["A1"]}


def test_valid_selection_is_local_and_loss_is_not_classifier_input():
    client = Classifier()
    model = Model()
    selector = BlueSelector(JevSettings(enabled=True), client)
    step, audit = selector.select(model, {"loss_pct": 23, "critical_parts": ["A1"]}, valid)
    assert step == CANDIDATES[0]
    assert audit["selector"] == "jev" and audit["selected_id"] == "c1"
    assert len(audit["candidates"]) == 3
    assert audit["llm_calls"] == 1 and audit["jev_calls"] == 1
    assert "loss_pct" not in json.dumps(client.calls)
    step["args"]["only_critical"] = False
    assert audit["candidates"][0]["args"]["only_critical"] is True


def test_invalid_id_falls_back_without_executing_classifier_arguments():
    step, audit = BlueSelector(JevSettings(enabled=True), Classifier("evil")).select(Model(), {}, valid)
    assert step is None and audit["fallback"] and audit["selector"] == "existing_blue"


def test_disabled_makes_no_calls_or_previews():
    model, client = Model(), Classifier()
    step, audit = BlueSelector(JevSettings(), client).select(model, {}, lambda _: pytest.fail("preview"))
    assert step is None and not audit["fallback"]
    assert not model.calls and not client.calls


@pytest.mark.parametrize("failure", ["timeout", "invalid", "access"])
def test_http_failures_return_to_blue(monkeypatch, failure):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "offline-test-key")
    def handler(request):
        assert request.url.path == "/v1/classifier"
        body = json.loads(request.content)
        assert body["questions"]["blue"]["type"] == "choice"
        assert "messages" not in body and "temperature" not in body
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider text", request=request)
        if failure == "access":
            return httpx.Response(403, json={"error": "private provider text"})
        return httpx.Response(200, json={"answers": {"blue": {"type": "choice", "choice": "unknown"}}})
    cfg = JevSettings(enabled=True)
    client = FeatherlessClassifier(cfg, transport=httpx.MockTransport(handler))
    step, audit = BlueSelector(cfg, client).select(Model(), {}, valid)
    assert step is None and audit["fallback"] and audit["jev_calls"] == 1
    assert audit["request_ms"] >= 0
    assert "private" not in str(audit) and "offline-test-key" not in str(audit)


def test_http_valid_schema(monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "offline-test-key")
    def handler(request):
        return httpx.Response(200, json={"answers": {"blue": {"type": "choice", "choice": "c1",
            "confidence": 0.8, "probabilities": {"c1": 0.8, "c2": 0.2}}}})
    client = FeatherlessClassifier(JevSettings(), transport=httpx.MockTransport(handler))
    result = client.choose({}, [{"id": "c1"}, {"id": "c2"}])
    assert result["selected_id"] == "c1" and result["confidence"] == 0.8


def test_invalid_and_duplicate_candidates_do_not_reach_jev():
    client = Classifier()
    step, audit = BlueSelector(JevSettings(enabled=True), client).select(Model(), {}, lambda _: None)
    assert step is None and audit["fallback"] and not client.calls


def test_confidence_threshold_preserves_reported_probabilities():
    step, audit = BlueSelector(JevSettings(enabled=True, min_confidence=0.9), Classifier()).select(Model(), {}, valid)
    assert step is None and audit["fallback"] and audit["confidence"] == 0.7


class Board:
    def __init__(self):
        self.losses = {"main": 0.2}
        self.edits = {"main": []}
        self.discarded = []
        self.lab = self
        self._deep_cache = {}
        self.next = 0

    def loss(self, branch):
        return self.losses[branch]

    def evaluate_branch(self, branch):
        return SimpleNamespace(critical_parts_unavailable=["A1"] if self.losses[branch] >= 0.15 else [])

    def stack(self, side, label, parent, actions):
        self.next += 1
        branch = str(self.next)
        self.edits[branch] = self.edits[parent] + actions
        self.losses[branch] = self.losses[parent] - (0.06 if actions[0]["action"] == "backup_all_affected_parts" else 0.03)
        return branch

    def discard(self, branch):
        self.discarded.append(branch)
        del self.losses[branch]
        del self.edits[branch]

    def options(self, side, head):
        return {"deep_candidates": CANDIDATES, "fallback": CANDIDATES[0]}

    def effects(self, *args):
        return {}


def test_match_executes_one_blue_action_and_records_measured_outcome(monkeypatch, tmp_path):
    import agents.blue_selection as module
    selector = BlueSelector(JevSettings(enabled=True), Classifier("c2"))
    monkeypatch.setattr(module, "BlueSelector", lambda: selector)
    board, model = Board(), Model(offered=True)
    match = Match(board, llm=model, rounds=1, directory=tmp_path)
    move = match._play("blue", 1)
    assert move.action == "add_backup_supplier" and len(move.actions) == 1
    assert len(board.discarded) == 3 and board.loss("main") == 0.2
    assert move.selection["impact"]["loss_after_pct"] == 17
    assert move.llm_calls == 2 and move.selection["jev_calls"] == 1
    assert move.rationale == "Protected critical parts."


def test_match_fallback_preserves_existing_action(monkeypatch, tmp_path):
    import agents.blue_selection as module
    monkeypatch.setattr(module, "BlueSelector", lambda: BlueSelector(JevSettings(enabled=True), Classifier("evil")))
    board, model = Board(), Model(offered=True)
    match = Match(board, llm=model, rounds=1, directory=tmp_path)
    move = match._play("blue", 1)
    assert move.action == "backup_all_affected_parts" and len(move.actions) == 1
    assert move.selection["fallback"] and move.llm_calls == 2
    assert model.calls[-1] == "blue"


def test_standalone_validates_stacking_discards_previews_and_explains(monkeypatch):
    import agents.defence as defence
    import agents.blue_selection as module
    import agents.tools as tools
    board = Board()
    board.ensure_ready = lambda: None
    board.spec_of = lambda branch: {"actions": [{"action": "strike_supplier", "args": {"supplier_id": "S1"}}]}
    original_evaluate = board.evaluate_branch
    def evaluate(branch):
        imp = original_evaluate(branch)
        imp.loss = board.loss(branch)
        imp.parts_unavailable = ["A1", "B1"]
        imp.suppliers_down = []
        imp.sites_down = []
        return imp
    board.evaluate_branch = evaluate
    calls = []
    def build(lab, role, label, parent, steps):
        calls.append((parent, steps))
        branch = board.stack("blue", label, parent, steps)
        return {"change_id": branch, "loss_pct": round(100 * board.loss(branch), 1)}
    monkeypatch.setattr(tools, "build_stacked", build)
    monkeypatch.setattr(module, "BlueSelector", lambda: BlueSelector(JevSettings(enabled=True), Classifier("c2")))
    model = Model()
    trace = defence.run_defence(board, model, "main")
    assert trace.result["selection"]["selector"] == "jev"
    assert trace.result["countermeasures"] == [CANDIDATES[1]]
    assert trace.result["loss_after_pct"] == 17
    assert trace.result["explanation"] == "Protected critical parts."
    assert len(board.discarded) == 3
    assert all(parent == "main" and len(steps) == 1 for parent, steps in calls)
    assert trace.result["selection"]["total_llm_calls"] == 2


def test_standalone_disabled_delegates_without_additional_work(monkeypatch):
    import agents.defence as defence
    import agents.blue_selection as module
    from agents.engine import Trace
    expected = Trace("defence", result={"defence_branch": "old"})
    monkeypatch.setattr(module, "BlueSelector", lambda: BlueSelector(JevSettings(), Classifier()))
    seen = []
    monkeypatch.setattr(defence, "_run_existing", lambda *args: seen.append(args) or expected)
    assert defence.run_defence(None, None, "old", 4) is expected
    assert seen == [(None, None, "old", 4, None)]


def test_production_failure_never_silently_switches_to_demo(monkeypatch):
    from agents.jev import JevError
    monkeypatch.setenv("FEATHERLESS_API_KEY", "offline-key")
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == "api.featherless.ai"
        assert request.headers["authorization"] == "Bearer offline-key"
        return httpx.Response(400, json={"error": {"message": "rejected"}})
    client = FeatherlessClassifier(JevSettings(), transport=httpx.MockTransport(handler))
    with pytest.raises(JevError, match="http_400"):
        client.choose({}, [{"id": "c1"}, {"id": "c2"}])
    assert len(requests) == 1
