"""Live, end-to-end agent tests: real Featherless model calls driving real TuringDB branches. Skipped
unless both are available. These are the integration tests the build is meant to prove, so they are not
mocked; they use small step budgets to stay within a few minutes."""

from __future__ import annotations

import pytest

from tests.agents.conftest import featherless_available, turingdb_reachable

pytestmark = pytest.mark.skipif(
    not (turingdb_reachable() and featherless_available()),
    reason="needs TuringDB theatre graph and the Featherless API key",
)


def test_featherless_call_returns_parseable_action(llm):
    from agents.llm import parse_action

    reply = llm.chat(
        [{"role": "system", "content": 'Reply with one JSON object {"thought":..,"action":..,"args":{}}.'},
         {"role": "user", "content": 'Call tool "ping" with arg n=1.'}],
        agent="test")
    action = parse_action(reply)
    assert action["action"] and isinstance(action["args"], dict)
    assert llm.usage.calls >= 1


def test_threat_agent_explores_branches(lab, llm):
    from agents.threat import run_threat

    trace = run_threat(lab, llm, max_steps=12)
    threat_branches = [r for r in lab.records() if r.role == "threat" and r.loss is not None]
    assert len(threat_branches) >= 2  # it tested multiple strategies, each its own branch
    assert any(r.loss > 0 for r in threat_branches)  # at least one strategy caused loss
    assert trace.result is not None


def test_defence_agent_reduces_worst_threat(lab, llm):
    from agents.defence import run_defence
    from agents.threat import run_threat

    run_threat(lab, llm, max_steps=12)
    worst = max((r for r in lab.records() if r.role == "threat" and r.loss is not None),
               key=lambda r: r.loss)
    assert worst.loss > 0
    run_defence(lab, llm, worst.change_id, max_steps=14)
    defences = [r for r in lab.records() if r.role == "defence" and r.loss is not None]
    assert defences
    best = min(defences, key=lambda r: r.loss)
    assert best.loss < worst.loss  # the defence genuinely reduced projected loss

    diff = lab.diff_impacts(worst.change_id, best.change_id)
    assert diff["loss_b_pct"] < diff["loss_a_pct"]


def test_scenario_agent_simulates_and_diffs(lab, llm):
    from agents.scenario import run_scenario

    question = ("A catastrophic event has destroyed everything across Manchester. How would this affect "
                "the rest of the city and its connected infrastructure?")
    trace = run_scenario(lab, llm, question, max_steps=16)
    assert any(s.action == "simulate_scenario" for s in trace.steps)  # NL -> branch simulation happened
    scenarios = [r for r in lab.records() if r.role == "scenario"]
    assert scenarios, "the scenario agent built no branch"
    # ground truth: the simulated catastrophe destroyed nodes on the branch (count drops vs main)
    destroyed = [r for r in scenarios if _nodes_destroyed(lab, r.change_id) > 0]
    assert destroyed, "no scenario branch actually destroyed any node"
    branch = destroyed[-1]
    # and the destruction is visible through a TuringDB diff (what drives the map overlay)
    graph = lab.diff_graph("main", branch.change_id)
    assert graph["removed"] or lab.evaluate_branch(branch.change_id).loss > 0
    assert isinstance(trace.result, dict)


def _nodes_destroyed(lab, change_id: str) -> int:
    labels = ("PowerPlant", "Site", "Drone", "Location", "Crime", "Person", "Supplier")
    main, branch = lab.graph.session("main"), lab.graph.session(change_id)
    total = 0
    for label in labels:
        m = int(main.q(f"MATCH (n:{label}) RETURN count(n) AS c")["c"].iloc[0])
        b = int(branch.q(f"MATCH (n:{label}) RETURN count(n) AS c")["c"].iloc[0])
        total += max(0, m - b)
    return total
