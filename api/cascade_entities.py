"""Cascade origins beyond chokepoints, ports and facilities: companies, countries, power plants and supply items.

Each of these reaches the deep supply network through exactly one edge into Facility, so its loss seeds the same
volume-weighted cascade: a company's facilities (OPERATED_BY), a country's facilities (LOCATED_IN), the
facilities a plant powers (POWERED_BY, severity = share of that facility's power feeds) and the facilities that
make an item (PRODUCED_AT). Anything with no such edge is reported as not connected to the supply network.
"""

from __future__ import annotations

from typing import Mapping

from api.models import OriginKind

ENTITY_LABELS: dict[str, OriginKind] = {
    "Company": "company",
    "Country": "country",
    "PowerPlant": "plant",
    "Mineral": "item",
    "Material": "item",
    "Component": "item",
    "Assembly": "item",
    "Subassembly": "item",
    "Subsystem": "item",
    "System": "item",
}
ENTITY_KINDS = frozenset(ENTITY_LABELS.values())

# kind -> (pattern from the origin `o` to its seed facilities `f`, edge type reported as `via`)
ENTITY_SEED: dict[str, tuple[str, str]] = {
    "company": ("(o)<-[:OPERATED_BY]-(f:Facility)", "OPERATED_BY"),
    "country": ("(o)<-[:LOCATED_IN]-(f:Facility)", "LOCATED_IN"),
    "plant": ("(o)<-[:POWERED_BY]-(f:Facility)", "POWERED_BY"),
    "item": ("(o)-[:PRODUCED_AT]->(f:Facility)", "PRODUCED_AT"),
}

POWER_FEEDS_Q = "MATCH (f:Facility)-[:POWERED_BY]->(p:PowerPlant) RETURN f.facility_id AS fid, count(p) AS n"


def entity_severities(kind: str, fids: list[str], power_feeds: Mapping[str, int]) -> dict[str, float]:
    """Seed severity per facility: a lost plant removes one of the facility's power feeds; the rest remove all."""
    if kind != "plant":
        return {fid: 1.0 for fid in fids}
    return {fid: 1.0 / max(1, power_feeds.get(fid, 1)) for fid in fids}
