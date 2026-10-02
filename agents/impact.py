"""Projected supply-chain loss of a graph state (main, or any branch), read entirely from TuringDB.

Demand: every (Site, Part) pair with purchase orders, weighted by PO count x part criticality
(A=5, B=2, C=1), taken from main once. On the evaluated ref:
    Supplier works  <=> it exists, has >= 1 POWERED_BY feed and >= 1 SOURCES_FROM logistics partner
    Part available  <=> >= 1 SUPPLIED_BY supplier works (backup suppliers count)
    Site works      <=> it exists and has >= 1 POWERED_BY feed
    capability = sum(weight of pairs whose site works and part is available) / sum(all weights)
    projected loss = 1 - capability
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from api.backends.turing_session import Session

CRITICALITY_WEIGHT = {"A": 5.0, "B": 2.0, "C": 1.0}


@dataclass(frozen=True)
class Demand:
    weights: dict[tuple[str, str], float]  # (site node id, part node id) -> weight
    site_names: dict[str, str]
    part_names: dict[str, str]
    part_class: dict[str, str]
    total: float


@dataclass
class Impact:
    loss: float  # 0..1
    capability: float
    site_loss: dict[str, float]  # site name -> loss share 0..1 of its own demand
    sites_down: list[str]
    suppliers_down: list[str]  # supplier_id of part suppliers that exist but do not work, or are gone
    parts_unavailable: list[str]  # part_id
    critical_parts_unavailable: list[str]  # class A part_id
    queries: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "projected_loss_pct": round(100 * self.loss, 1),
            "site_loss_pct": {k: round(100 * v, 1) for k, v in sorted(self.site_loss.items())},
            "sites_down": self.sites_down,
            "suppliers_down": self.suppliers_down,
            "parts_unavailable": len(self.parts_unavailable),
            "critical_parts_unavailable": len(self.critical_parts_unavailable),
            "example_critical_parts": self.critical_parts_unavailable[:8],
        }


def load_demand(main: Session) -> Demand:
    frame = main.q("MATCH (s:Site)<-[:DELIVERED_TO]-(po:PurchaseOrder)-[:FOR_PART]->(p:Part) "
                   "RETURN s, p, s.site_id AS site, p.part_id AS part, p.criticality_class AS cc")
    weights: dict[tuple[str, str], float] = defaultdict(float)
    site_names, part_names, part_class = {}, {}, {}
    for s, p, site, part, cc in frame.itertuples(index=False):
        key = (str(s), str(p))
        weights[key] += CRITICALITY_WEIGHT.get(str(cc), 1.0)
        site_names[str(s)], part_names[str(p)], part_class[str(p)] = str(site), str(part), str(cc)
    return Demand(dict(weights), site_names, part_names, part_class, sum(weights.values()))


def evaluate(s: Session, demand: Demand) -> Impact:
    sw_before = len(s.sw.traces)
    sites = {str(x) for x in s.q("MATCH (x:Site) RETURN x")["x"]}
    powered_sites = {str(x) for x in s.q("MATCH (x:Site)-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
    sup = s.q("MATCH (x:Supplier) WHERE x.source = 'supply_chain' RETURN x, x.supplier_id AS sid")
    sup_ids = {str(x): str(sid) for x, sid in sup.itertuples(index=False)}
    powered_sups = {str(x) for x in s.q("MATCH (x:Supplier)-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
    routed = {str(x) for x in s.q("MATCH (x:Supplier)-[:SOURCES_FROM]->(l:Supplier) RETURN x")["x"]}
    working = {x for x in sup_ids if x in powered_sups and x in routed}
    supplied = s.q("MATCH (p:Part)-[:SUPPLIED_BY]->(x:Supplier) RETURN p, x")
    available = {str(p) for p, x in supplied.itertuples(index=False) if str(x) in working}
    working_sites = sites & powered_sites

    lost_by_site: dict[str, float] = defaultdict(float)
    total_by_site: dict[str, float] = defaultdict(float)
    for (site, part), w in demand.weights.items():
        total_by_site[site] += w
        if site not in working_sites or part not in available:
            lost_by_site[site] += w
    lost = sum(lost_by_site.values())
    loss = lost / demand.total if demand.total else 0.0
    unavailable = sorted(demand.part_names[p] for p in demand.part_names if p not in available)
    critical = sorted(demand.part_names[p] for p in demand.part_names
                      if p not in available and demand.part_class.get(p) == "A")
    # suppliers deleted on this ref are reported by the caller (they no longer resolve to an id here)
    down = sorted(sid for x, sid in sup_ids.items() if x not in working)
    return Impact(
        loss=loss, capability=1 - loss,
        site_loss={demand.site_names[s_]: lost_by_site[s_] / total_by_site[s_] for s_ in total_by_site},
        sites_down=sorted(demand.site_names[x] for x in total_by_site if x not in working_sites),
        suppliers_down=down, parts_unavailable=unavailable, critical_parts_unavailable=critical,
        queries=[t.cypher for t in s.sw.traces[sw_before:]],
    )
