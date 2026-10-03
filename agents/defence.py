"""Defence agent: analyse the most damaging threat scenario and develop countermeasures.

It reads a threat branch, then tests countermeasures — each in its own branch that replays the attack and
adds the mitigation — and measures how much projected loss each removes. It keeps every branch so
countermeasure sets can be compared, and reports the set that cuts loss the most.
"""

from __future__ import annotations

import logging

from agents.branches import BranchLab
from agents.engine import Agent, Step, StepListener, Tool, Trace
from agents.llm import FeatherlessLLM
from agents.tools import build_branch, diff_tool, impact_tool, query_tool, schema_tool

log = logging.getLogger("agents.defence")

SYSTEM = """You are the DEFENCE agent for a supply-chain resilience study. The threat agent has produced a
damaging scenario on a branch. Your job: develop countermeasures that reduce its projected loss, and prove
the reduction with branches and diffs.

Method:
1. Call `describe_threat` to see the attack and exactly which parts/suppliers/sites it knocked out.
2. Propose countermeasures. Each defence branch REPLAYS the attack and then adds mitigations, so its loss
   is comparable to the threat branch. Test a branch with `test_defence`.
3. Add mitigations until projected loss is low. Prefer the SMALLEST, simplest set that works; try the
   different countermeasure TYPES (backup supplier, alternative route, power feed, air-defence), not just
   one type repeated. Note: a supplier destroyed by the attack cannot be rerouted — add a backup supplier
   for its parts, or restore power / air-defence to the facilities that depend on it instead.
4. Use `diff` to confirm the loss before vs after.
5. `finish` with: defence_branch (change_id), loss_before_pct, loss_after_pct, and the list of
   countermeasures you chose.

Countermeasure steps available inside test_defence (args as shown):
  {"action":"backup_all_affected_parts","args":{}}                     qualify a backup supplier for EVERY
                                                                       part the attack left unavailable (the
                                                                       most effective single countermeasure;
                                                                       add {"only_critical":true} for class-A only)
  {"action":"add_backup_supplier","args":{"part_id":"P00020"}}        add a backup supplier for one part
  {"action":"reroute_supplier","args":{"supplier_id":"SUP013"}}        add an alternative logistics route
  {"action":"restore_power","args":{"facility_id":"SITE04"}}           add an alternative power feed
  {"action":"prioritise_air_defence","args":{"gppd_idnr":"WRI1006130"}} protect a plant + restore feeds
Tip: try `backup_all_affected_parts` to see the maximum achievable reduction, then, if you want a smaller
set, test targeted measures and compare.
You do NOT need to list the attack steps yourself; describe_threat gives them and test_defence replays them."""


def build_defence_agent(lab: BranchLab, llm: FeatherlessLLM, threat_branch: str, max_steps: int = 16) -> Agent:
    rec = lab.record(threat_branch)
    attack_actions = rec.spec.get("actions", []) if rec else []

    def describe_threat() -> dict:
        imp = lab.evaluate_branch(threat_branch)
        return {"threat_branch": threat_branch, "label": rec.label if rec else "?",
                "attack_steps": attack_actions, "loss_pct": round(100 * imp.loss, 1),
                "parts_unavailable": imp.parts_unavailable[:40],
                "critical_parts_unavailable": imp.critical_parts_unavailable,
                "suppliers_down": imp.suppliers_down, "sites_down": imp.sites_down}

    def test_defence(label: str, countermeasures: list[dict]) -> dict:
        if not isinstance(countermeasures, list) or not countermeasures:
            return {"error": "countermeasures must be a non-empty list of {action, args} steps"}
        actions = list(attack_actions) + list(countermeasures)
        result = build_branch(lab, "defence", label, actions, parent=threat_branch)
        if "error" not in result:
            threat_loss = lab.evaluate_branch(threat_branch).loss
            result["loss_before_pct"] = round(100 * threat_loss, 1)
            result["loss_after_pct"] = result["loss_pct"]
            result["reduction_pct"] = round(100 * (threat_loss - result["loss_pct"] / 100), 1)
            result["countermeasures"] = countermeasures
        return result

    tools = [
        Tool("describe_threat", "The threat branch's attack and what it knocked out (parts, suppliers, "
             "sites).", describe_threat),
        Tool("test_defence", "Open a new branch that replays the attack then applies your countermeasures, "
             "and return loss before vs after. The branch is kept for comparison.", test_defence,
             {"label": "short name for this defence", "countermeasures": "list of {action, args} steps"}),
        diff_tool(lab), impact_tool(lab), query_tool(lab),
    ]
    return Agent("defence", llm, SYSTEM, tools, max_steps=max_steps)


def _run_existing(lab: BranchLab, llm: FeatherlessLLM, threat_branch: str, max_steps: int = 16,
                on_step: StepListener | None = None) -> Trace:
    lab.ensure_ready()
    agent = build_defence_agent(lab, llm, threat_branch, max_steps)
    return agent.run(f"Develop countermeasures for threat branch {threat_branch} and report the loss "
                     "reduction, proven with a diff.", on_step)


def run_defence(lab: BranchLab, llm: FeatherlessLLM, threat_branch: str, max_steps: int = 16,
                on_step: StepListener | None = None) -> Trace:
    from agents.blue_selection import BlueSelector
    from agents.match import _TimedModel
    from agents.tools import build_stacked
    import time

    selector = BlueSelector()
    if not selector.settings.enabled:
        trace = _run_existing(lab, llm, threat_branch, max_steps, on_step)
        trace.result = {**(trace.result or {}), "selection": {
            "selector": "existing_blue", "fallback": False, "candidates": [], "jev_calls": 0}}
        return trace
    lab.ensure_ready()
    started = time.perf_counter()
    timed = _TimedModel(llm)
    before = lab.evaluate_branch(threat_branch)
    state = {"parts_unavailable": before.parts_unavailable[:40],
             "critical_parts_unavailable": before.critical_parts_unavailable[:40],
             "suppliers_down": before.suppliers_down[:20], "sites_down": before.sites_down,
             "attack": lab.spec_of(threat_branch).get("actions", []),
             "budget": "unspecified; standalone dataset has no intervention costs or deadlines"}

    def validate(step):
        built = build_stacked(lab, "defence", "Blue candidate preview", threat_branch, [step])
        if "error" in built:
            return None
        branch = str(built["change_id"])
        try:
            after = lab.evaluate_branch(branch)
            return {"loss_pct": round(100 * after.loss, 1),
                    "critical_parts_restored": sorted(set(before.critical_parts_unavailable) -
                                                       set(after.critical_parts_unavailable)),
                    "parts_restored_count": len(set(before.parts_unavailable) - set(after.parts_unavailable)),
                    "sites_restored": sorted(set(before.sites_down) - set(after.sites_down))}
        finally:
            lab.discard(branch)

    step, audit = selector.select(timed, state, validate)
    built = build_stacked(lab, "defence", "Priority-selected Blue defence", threat_branch, [step]) if step else None
    if built and "error" not in built:
        branch = str(built["change_id"])
        audit["impact"] = {"loss_before_pct": round(100 * before.loss, 1), "loss_after_pct": built["loss_pct"]}
        explanation = selector.explain(timed, audit, audit["impact"])
        result = {"defence_branch": branch, **audit["impact"], "countermeasures": [step],
                  "explanation": explanation, "selection": audit}
        trace = Trace("defence", [Step(explanation, "blue_selection", {}, result)], result, timed.model)
    else:
        if step:
            audit.update(selector="existing_blue", fallback=True, reason="execution_rejected")
        trace = _run_existing(lab, timed, threat_branch, max_steps, on_step)
        trace.result = {**(trace.result or {}), "selection": audit}
        chosen = trace.result.get("defence_branch")
        if chosen and lab.record(str(chosen)):
            audit["impact"] = {"loss_before_pct": round(100 * before.loss, 1),
                               "loss_after_pct": round(100 * lab.evaluate_branch(str(chosen)).loss, 1)}
        trace.steps.append(Step("Existing Blue flow selected the defence.", "blue_selection", {}, audit))
    audit.update(total_ms=round((time.perf_counter() - started) * 1000, 1), total_llm_calls=timed.calls, total_llm_requests=timed.requests)
    if on_step:
        on_step("defence", trace.steps[-1])
    return trace
