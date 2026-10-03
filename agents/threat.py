"""Threat agent: find the disruptions that cost the supply chain the most for the fewest attacks.

It explores the graph, ranks high-leverage targets, and tests each candidate attack strategy in its own
TuringDB branch (keeping every branch so strategies can be compared). It only reasons at the level of
infrastructure dependencies and projected loss; it produces no operational attack instructions.
"""

from __future__ import annotations

import logging

from agents.branches import BranchLab
from agents.engine import Agent, StepListener, Tool, Trace
from agents.llm import FeatherlessLLM
from agents.tools import branches_tool, build_branch, impact_tool, query_tool, schema_tool

log = logging.getLogger("agents.threat")

SYSTEM = """You are the THREAT-MODELLING agent for a defence supply-chain resilience study.
Your goal: identify which targets, if disrupted, would cause the MAXIMUM projected loss to the supply
chain for the MINIMUM number of attacks. This is a defensive risk assessment — you are finding the supply
chain's own worst single points of failure so the defence agent can harden them. Stay at the level of
graph dependencies and projected loss percentages. Never produce real-world operational instructions.

Method:
1. Use `scout_targets` to see the highest-leverage suppliers and plants (by critical-part demand).
2. Form competing strategies. Each strategy is a list of attack steps. Test each with `test_attack`,
   which opens a NEW branch, applies the attacks there (never to main), and returns the projected loss and
   the number of attacks. Test:
     - at least two single-attack strategies (one attack each), to find the most efficient single target;
     - at least one COMBINED strategy that strikes the top 4-6 suppliers together, to find how much damage
       a small coordinated campaign causes (maximum-damage dimension).
   A combined strike puts several steps in one actions list, e.g.
   [{"action":"strike_supplier","args":{"supplier_id":"SUP012"}}, {"action":"strike_supplier","args":{"supplier_id":"SUP013"}}].
3. Compare strategies on the damage-vs-attacks frontier. The worst_branch is the one with the highest
   projected loss (your maximum-damage finding); also note the most efficient single attack.
4. `finish` with: worst_branch (change_id of the highest-loss strategy), most_efficient_branch (change_id),
   a ranking list (change_id, label, loss_pct, attacks), and a short rationale.

Attack steps available inside test_attack (args as shown):
  {"action":"strike_supplier","args":{"supplier_id":"SUP013"}}   remove a part supplier
  {"action":"strike_plant","args":{"gppd_idnr":"WRI1006130"}}    remove a power plant
  {"action":"cut_route","args":{"supplier_id":"SUP013"}}          cut a supplier's logistics routes
Prefer the fewest attacks that still cause large loss."""


def scout_targets(lab: BranchLab, branch: str = "main") -> dict:
    """Rank part suppliers by criticality-weighted demand and list the biggest plants — the leverage points."""
    s = lab.graph.session(branch)
    frame = s.q("MATCH (sup:Supplier)<-[:SUPPLIED_BY]-(p:Part) WHERE sup.source = 'supply_chain' "
                "RETURN sup, sup.supplier_id AS sid, p.part_id AS part, p.criticality_class AS cc")
    weight = {"A": 5.0, "B": 2.0, "C": 1.0}
    agg: dict[str, dict] = {}
    for _, sid, _, cc in frame.itertuples(index=False):
        bare = str(sid).split(":")[-1]
        a = agg.setdefault(bare, {"supplier_id": bare, "parts": 0, "class_A_parts": 0, "weight": 0.0})
        a["parts"] += 1
        a["class_A_parts"] += str(cc) == "A"
        a["weight"] += weight.get(str(cc), 1.0)
    ranked = sorted(agg.values(), key=lambda a: -a["weight"])[:12]
    plants = s.q("MATCH (pp:PowerPlant)<-[:POWERED_BY]-(x:Site) RETURN pp, pp.gppd_idnr AS g, pp.name AS n, "
                 "pp.capacity_mw AS mw")
    big = sorted({str(g): {"gppd_idnr": str(g), "name": str(n), "capacity_mw": float(mw or 0)}
                  for _, g, n, mw in plants.itertuples(index=False)}.values(),
                 key=lambda p: -p["capacity_mw"])[:8]
    return {"top_suppliers_by_critical_demand": ranked, "site_feeding_plants": big,
            "note": "each part has a single primary supplier, so removing a supplier makes all its parts "
                    "unavailable unless a backup exists"}


def build_threat_agent(lab: BranchLab, llm: FeatherlessLLM, max_steps: int = 16) -> Agent:
    def test_attack(label: str, actions: list[dict]) -> dict:
        return build_branch(lab, "threat", label, actions)

    tools = [
        Tool("scout_targets", "Ranked high-leverage targets: suppliers by critical-part demand, biggest "
             "site-feeding plants.", lambda: scout_targets(lab)),
        Tool("test_attack", "Open a new branch, apply a list of attack steps there, and return its "
             "projected loss and attack count. The branch is kept for comparison.", test_attack,
             {"label": "short name for this strategy", "actions": "list of {action, args} attack steps"}),
        query_tool(lab), impact_tool(lab), branches_tool(lab, role="threat"),
    ]
    return Agent("threat", llm, SYSTEM, tools, max_steps=max_steps)


def run_threat(lab: BranchLab, llm: FeatherlessLLM, max_steps: int = 16,
               on_step: StepListener | None = None) -> Trace:
    lab.ensure_ready()
    agent = build_threat_agent(lab, llm, max_steps)
    return agent.run("Find the most damaging, most efficient disruption strategies and report the worst branch.",
                     on_step)
