"""Service availability over the authoritative DEPENDS_ON graph at one instant.

availability(n) = physical(n) x min over n's dependency groups of the group value, where
- a required group (electricity, communications, water, crossing, ...) is the minimum of its providers;
- `material_input` is a share-weighted mixture: sum(share x provider) / sum(share). A missing provider keeps
  its share in the denominator, so losing the 60% import leaves a distribution centre at 40%.
Local recovery enters only through `Conditions`: generator-fed loads, delivered cargo at import customs and
released stock at a service. Nothing here knows about time; simulate.py calls it once per time segment.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from agents.resilience.network import Dependency, Network

INFLOW_GROUPS = frozenset({"crossing", "material_input"})  # import customs: replaced by delivered cargo
FULL = 0.999  # availability at or above this counts as fully served (float noise from share sums)
EMPTY: Mapping[str, float] = MappingProxyType({})


@dataclass(frozen=True)
class Conditions:
    down: frozenset[str]  # physically unavailable now (event targets)
    powered: frozenset[str] = frozenset()  # electricity supplied by an allocated generator
    inflow: Mapping[str, float] = field(default_factory=lambda: EMPTY)  # receiver -> delivered cargo fraction
    supply_extra: Mapping[str, float] = field(default_factory=lambda: EMPTY)  # service -> released stock fraction


def grouped(deps: tuple[Dependency, ...]) -> dict[str, list[Dependency]]:
    out: dict[str, list[Dependency]] = defaultdict(list)
    for d in deps:
        out[d.group].append(d)
    return out


def group_value(eid: str, group: str, deps: list[Dependency], avail: Mapping[str, float], cond: Conditions) -> float:
    if group in INFLOW_GROUPS and eid in cond.inflow:
        return cond.inflow[eid]
    if group == "electricity" and eid in cond.powered:
        return 1.0
    if group == "material_input":
        total = sum(d.share if d.share is not None else 1.0 for d in deps)
        value = sum((d.share if d.share is not None else 1.0) * avail.get(d.provider, 1.0) for d in deps) / total
    else:
        value = min(avail.get(d.provider, 1.0) for d in deps)
    if group == "consumables":
        value = min(1.0, value + cond.supply_extra.get(eid, 0.0))
    return value


def evaluate(net: Network, cond: Conditions) -> dict[str, float]:
    """Availability of every node in the dependency graph (others are 1.0, or 0.0 when down)."""
    avail: dict[str, float] = {eid: 0.0 for eid in cond.down}
    for eid in net.order:
        if eid in cond.down:
            continue
        value = 1.0
        for group, deps in grouped(net.depends.get(eid, ())).items():
            value = min(value, group_value(eid, group, deps, avail, cond))
        avail[eid] = value
    return avail


def has_power(net: Network, eid: str, avail: Mapping[str, float], cond: Conditions) -> bool:
    """Whether the asset's electricity group is satisfied (cold-chain storage needs this)."""
    if eid in cond.down:
        return False
    if eid in cond.powered:
        return True
    deps = [d for d in net.depends.get(eid, ()) if d.group == "electricity"]
    return all(avail.get(d.provider, 1.0) >= FULL for d in deps)


def operable(net: Network, eid: str, avail: Mapping[str, float], cond: Conditions) -> float:
    """Availability ignoring the consumables group: can the service hand out goods if it has them?"""
    if eid in cond.down:
        return 0.0
    value = 1.0
    for group, deps in grouped(net.depends.get(eid, ())).items():
        if group != "consumables":
            value = min(value, group_value(eid, group, deps, avail, cond))
    return value
