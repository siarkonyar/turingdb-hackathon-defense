"""Defence agent: analyse the most damaging threat scenario and develop countermeasures.

It reads a threat branch, then tests countermeasures — each in its own branch that replays the attack and
adds the mitigation — and measures how much projected loss each removes. It keeps every branch so
countermeasure sets can be compared, and reports the set that cuts loss the most.
"""

from __future__ import annotations

import logging

from agents.branches import BranchLab
from agents.engine import Agent, Tool, Trace
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


def run_defence(lab: BranchLab, llm: FeatherlessLLM, threat_branch: str, max_steps: int = 16) -> Trace:
    lab.ensure_ready()
    agent = build_defence_agent(lab, llm, threat_branch, max_steps)
    return agent.run(f"Develop countermeasures for threat branch {threat_branch} and report the loss "
                     "reduction, proven with a diff.")
