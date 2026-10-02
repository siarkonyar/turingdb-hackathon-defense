"""Live branch-lab tests against TuringDB (no LLM): branches are the search space, and impact + diffs are
read from graph state. Skipped when TuringDB/theatre is unavailable."""

from __future__ import annotations

import pytest

from agents.actions import apply_action
from tests.agents.conftest import turingdb_reachable

pytestmark = pytest.mark.skipif(not turingdb_reachable(), reason="TuringDB theatre graph not available")


def _supplier_strike(lab, supplier="SUP012"):
    spec = {"actions": [{"action": "strike_supplier", "args": {"supplier_id": supplier}}]}
    s, rec = lab.open_branch("threat", f"Strike {supplier}", spec)
    apply_action(lab, s, "strike_supplier", {"supplier_id": supplier})
    return s, rec


def test_baseline_is_nominal(lab):
    assert lab.baseline.loss == pytest.approx(0.0, abs=1e-9)


def test_attack_branch_raises_loss_and_keeps_main_clean(lab):
    _, rec = _supplier_strike(lab)
    imp = lab.evaluate_branch(rec.change_id)
    assert imp.loss > 0
    assert imp.parts_unavailable  # the struck supplier's parts are now unavailable
    # main is untouched: still nominal
    from api.backends.turing_session import Session
    from api.refs import Ref
    from api.support import Stopwatch
    from agents.impact import evaluate
    main = Session(lab.graph.host, lab.graph.graph, Ref("main"), Stopwatch("turingdb"))
    assert evaluate(main, lab.demand).loss == pytest.approx(0.0, abs=1e-9)
    lab.discard(rec.change_id)


def test_defence_branch_reduces_loss(lab):
    _, threat = _supplier_strike(lab, "SUP012")
    timp = lab.evaluate_branch(threat.change_id)
    attack = [{"action": "strike_supplier", "args": {"supplier_id": "SUP012"}}]
    defence = [{"action": "add_backup_supplier", "args": {"part_id": p}} for p in timp.parts_unavailable]
    s, drec = lab.open_branch("defence", "Backups", {"actions": attack + defence}, parent=threat.change_id)
    for step in attack + defence:
        apply_action(lab, s, step["action"], step.get("args", {}))
    dimp = lab.evaluate_branch(drec.change_id)
    assert dimp.loss < timp.loss  # countermeasures cut the loss
    lab.discard(threat.change_id)
    lab.discard(drec.change_id)


def test_diff_reports_loss_reduction(lab):
    _, threat = _supplier_strike(lab, "SUP013")
    timp = lab.evaluate_branch(threat.change_id)
    attack = [{"action": "strike_supplier", "args": {"supplier_id": "SUP013"}}]
    defence = [{"action": "add_backup_supplier", "args": {"part_id": p}} for p in timp.parts_unavailable]
    s, drec = lab.open_branch("defence", "Backups2", {"actions": attack + defence}, parent=threat.change_id)
    for step in attack + defence:
        apply_action(lab, s, step["action"], step.get("args", {}))
    diff = lab.diff_impacts(threat.change_id, drec.change_id)
    assert diff["loss_a_pct"] > diff["loss_b_pct"]
    assert diff["loss_delta_pct"] < 0
    assert set(diff["per_site"]) == {f"SITE0{i}" for i in range(1, 7)}
    lab.discard(threat.change_id)
    lab.discard(drec.change_id)


def test_scenario_wipe_marks_impact(lab):
    spec = {"actions": [
        {"action": "wipe_bbox", "args": {"west": -2.4, "south": 53.4, "east": -2.2, "north": 53.55}},
        {"action": "propagate", "args": {}},
    ]}
    s, rec = lab.open_branch("scenario", "Manchester wipe", spec)
    for step in spec["actions"]:
        apply_action(lab, s, step["action"], step.get("args", {}))
    imp = lab.evaluate_branch(rec.change_id)
    assert "SITE01" in imp.sites_down  # SITE01 sits in Manchester
    graph = lab.diff_graph("main", rec.change_id)
    assert graph["removed"]  # destroyed located nodes show up in the diff the map renders
    lab.discard(rec.change_id)
