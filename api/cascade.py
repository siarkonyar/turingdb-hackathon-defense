"""Dependency cascade shared by both backends.

Dependency edges point from the dependent to what it depends on, e.g.
    (Site)-[:POWERED_BY]->(PowerPlant)      (Part)-[:SUPPLIED_BY]->(Supplier)
    (Drone)-[:PATROLS]->(Site)              (Supplier)-[:SOURCES_FROM]->(Supplier)
    (PurchaseOrder)-[:FOR_PART]->(Part), (PurchaseOrder)-[:DELIVERED_TO]->(Site)  => Site depends on Part
Losing a node puts everything that (transitively) depends on it at risk. A backend only has to answer
"who depends on these nodes through rule R"; the walk, statuses, arcs and KPIs live here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

from api.models import Affected, Arc, Kpis, Node
from api.nodes import is_located, with_status

# label of the lost node -> dependency rules to follow backwards from it
RULES: dict[str, tuple[str, ...]] = {
    "PowerPlant": ("POWERED_BY",),
    "Supplier": ("SUPPLIED_BY", "SOURCES_FROM"),
    "Part": ("DELIVERED_TO",),
    "Site": ("PATROLS",),
    "Facility": ("SUPPLIES",),  # supply_chain_deep: a lost facility puts its buyers at risk
}
POWERED_LABELS = ("Site", "Supplier", "Facility")
MAX_HOPS = 6


@dataclass(frozen=True)
class Dependency:
    parent_id: str  # the node that was hit
    child: Node  # the node that depends on it
    rel: str


class DependencySource(Protocol):
    def dependents(self, label: str, ids: Sequence[str], rule: str) -> list[Dependency]:
        """Nodes depending on `ids` (all carrying `label`) through `rule`."""
        ...


def walk(struck: Node, source: DependencySource, max_hops: int = MAX_HOPS) -> list[Affected]:
    """Breadth-first walk over dependents; each node is reported once, at its shortest hop."""
    seen = {struck.id}
    frontier: list[Node] = [struck]
    affected: list[Affected] = []
    for hop in range(1, max_hops + 1):
        by_label: dict[str, list[str]] = defaultdict(list)
        for node in frontier:
            by_label[node.label].append(node.id)
        next_frontier: list[Node] = []
        for label, ids in sorted(by_label.items()):
            for rule in RULES.get(label, ()):
                for dep in source.dependents(label, ids, rule):
                    if dep.child.id in seen:
                        continue
                    seen.add(dep.child.id)
                    affected.append(Affected(node=dep.child, hop=hop, via=dep.rel, parent_id=dep.parent_id))
                    next_frontier.append(dep.child)
        if not next_frontier:
            break
        frontier = next_frontier
    return affected


def powered_ids(affected: Iterable[Affected]) -> list[str]:
    """Ids of affected facilities whose power feed was hit (candidates for 'no power')."""
    return [a.node.id for a in affected if a.via == "POWERED_BY" and a.node.label in POWERED_LABELS]


def apply_statuses(affected: Sequence[Affected], unpowered: set[str]) -> list[Affected]:
    return [a.model_copy(update={"node": with_status(a.node, "no_power" if a.node.id in unpowered else "at_risk")})
            for a in affected]


def build_arcs(struck: Node, affected: Sequence[Affected]) -> list[Arc]:
    """One arc per located affected node, drawn from its nearest located ancestor.
    Non-located hops (e.g. Parts) are collapsed, so Supplier -> Part -> Site draws Supplier -> Site."""
    nodes = {struck.id: struck} | {a.node.id: a.node for a in affected}
    parent = {a.node.id: a.parent_id for a in affected}
    arcs: list[Arc] = []
    for a in affected:
        if not is_located(a.node):
            continue
        anc = a.parent_id
        while anc in parent and not is_located(nodes[anc]):
            anc = parent[anc]
        origin = nodes.get(anc)
        if origin is None or not is_located(origin):
            continue
        arcs.append(Arc(source=(origin.lon, origin.lat), target=(a.node.lon, a.node.lat),
                        source_id=origin.id, target_id=a.node.id, hop=a.hop, rel=a.via))
    return arcs


def kpis(nodes_with_status: Iterable[Node]) -> Kpis:
    """Branch-wide KPIs from every node carrying a status on that branch."""
    at_risk = sites_np = sups_np = parts = 0
    for n in nodes_with_status:
        if n.label == "Part":
            parts += n.status is not None
        elif n.status == "at_risk" and is_located(n):
            at_risk += 1
        elif n.status == "no_power":
            sites_np += n.label == "Site"
            sups_np += n.label == "Supplier"
    return Kpis(assets_at_risk=at_risk, sites_without_power=sites_np,
                suppliers_without_power=sups_np, parts_affected=parts)
