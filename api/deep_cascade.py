"""Volume-weighted impact cascade over the deep supply network (pure: no I/O).

Why weighted: unweighted reach from one chokepoint touches half of all facilities and every platform, which
tells an operator nothing. Severity is the share of a facility's inbound supply volume that comes from
already-affected suppliers, so impact attenuates with depth and the map shows where it really bites.
Breadth-first: each facility is reported once, at the first degree that reaches it above the threshold.
Contract: docs/superpowers/plans/2026-10-03-cascade-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

MIN_SEVERITY = 0.05
MAX_DEGREE = 12
SEVERITY_DP = 3


@dataclass(frozen=True)
class SupplyNetwork:
    out_edges: Mapping[str, tuple[tuple[str, float], ...]]  # supplier facility_id -> ((buyer, volume), ...)
    inbound: Mapping[str, float]  # buyer facility_id -> total inbound volume over all its suppliers

    @staticmethod
    def from_edges(rows: Iterable[tuple[str, str, float | None]]) -> SupplyNetwork:
        out: dict[str, list[tuple[str, float]]] = {}
        inbound: dict[str, float] = {}
        for src, dst, volume in rows:
            v = max(0.0, float(volume or 0.0))
            out.setdefault(src, []).append((dst, v))
            inbound[dst] = inbound.get(dst, 0.0) + v
        return SupplyNetwork(out_edges={k: tuple(v) for k, v in out.items()}, inbound=inbound)


@dataclass(frozen=True)
class Seeds:
    severities: Mapping[str, float]  # facility_id -> severity in (0, 1]
    degree: int  # 1: seeds are the first affected facilities (chokepoint/port); 0: the seed is the lost origin
    via: str  # edge that carried the impact to the seeds: TRANSITED | LOADED_AT | SUPPLIES


@dataclass(frozen=True)
class Hit:
    facility_id: str
    degree: int
    severity: float
    parent: str | None  # parent facility_id; None when the parent is the (non-facility) origin
    via: str


def _sorted(items: Iterable[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(items, key=lambda kv: (-kv[1], kv[0]))


def _seed_layer(seeds: Seeds, min_severity: float) -> list[Hit]:
    kept = _sorted((fid, min(1.0, s)) for fid, s in seeds.severities.items() if s >= min_severity)
    return [Hit(fid, 1, round(s, SEVERITY_DP), None, seeds.via) for fid, s in kept]


def _next_layer(frontier: Sequence[str], severity: Mapping[str, float], seen: set[str],
                network: SupplyNetwork, degree: int, min_severity: float) -> list[Hit]:
    contrib: dict[str, float] = {}
    best: dict[str, tuple[float, str]] = {}
    for supplier in sorted(frontier):  # sorted: a tie on contribution keeps the smaller supplier id
        for buyer, volume in network.out_edges.get(supplier, ()):
            total = network.inbound.get(buyer, 0.0)
            if buyer in seen or total <= 0:
                continue
            share = severity[supplier] * volume / total
            contrib[buyer] = contrib.get(buyer, 0.0) + share
            if buyer not in best or share > best[buyer][0]:
                best[buyer] = (share, supplier)
    kept = _sorted((b, min(1.0, s)) for b, s in contrib.items() if s >= min_severity)
    return [Hit(b, degree, round(s, SEVERITY_DP), best[b][1], "SUPPLIES") for b, s in kept]


def propagate(seeds: Seeds, network: SupplyNetwork, min_severity: float = MIN_SEVERITY,
              max_degree: int = MAX_DEGREE) -> list[list[Hit]]:
    """Layers of hits, index 0 = degree 1. A facility origin (seed degree 0) is never returned itself."""
    if not 0 < min_severity <= 1:
        raise ValueError(f"min_severity must be in (0, 1], got {min_severity}")
    if seeds.degree not in (0, 1):
        raise ValueError(f"seed degree must be 0 or 1, got {seeds.degree}")
    layers: list[list[Hit]] = []
    if seeds.degree == 1:
        first = _seed_layer(seeds, min_severity)
        if not first:
            return []
        layers.append(first)
        severity = {h.facility_id: h.severity for h in first}
    else:
        severity = {fid: min(1.0, s) for fid, s in seeds.severities.items()}
    seen = set(severity)
    frontier = list(severity)
    degree = seeds.degree
    while frontier and degree < max_degree:
        degree += 1
        layer = _next_layer(frontier, severity, seen, network, degree, min_severity)
        if not layer:
            break
        layers.append(layer)
        for h in layer:
            severity[h.facility_id] = h.severity
            seen.add(h.facility_id)
        frontier = [h.facility_id for h in layer]
    return layers


def impact_score(layers: Sequence[Sequence[Hit]]) -> float:
    """Facility-equivalents of output disrupted: Σ severity over every hit (the origin is not a hit)."""
    return round(sum(h.severity for layer in layers for h in layer), 2)
