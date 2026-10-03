"""Live side of the impact cascade: reads the deep supply network from TuringDB on any ref (main or a branch),
times one deep variable-length query as proof of speed, and shapes the per-degree CascadeResponse the map
steps through. Read-only. The weighting itself lives in api/deep_cascade.py (pure, unit-tested)."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Sequence, TypeVar

import pandas as pd

from api.backends.turing import ENGINE, NODE_PROPS, TuringBackend
from api.backends.turing_session import Session, node_id_literal, string_literal
from api.deep_cascade import MAX_DEGREE, MIN_SEVERITY, Hit, Seeds, SupplyNetwork, propagate
from api.models import (Arc, CascadeHit, CascadeResponse, CascadeStage, Node, OriginKind, PlatformExposure,
                        ReachProbe)
from api.nodes import clean, is_located, with_status
from api.refs import Ref
from api.support import NotFound, Stopwatch

T = TypeVar("T")
CACHE_LIMIT = 24
ORIGIN_LABELS: dict[str, OriginKind] = {"Chokepoint": "chokepoint", "Port": "port", "Facility": "facility"}
KEY_PROP: dict[str, str] = {"chokepoint": "waypoint_id", "port": "port_id", "facility": "facility_id"}
LABEL_OF: dict[str, str] = {"chokepoint": "Chokepoint", "port": "Port", "facility": "Facility"}
SEED_EDGE: dict[str, str] = {"chokepoint": "TRANSITED", "port": "LOADED_AT"}

SUPPLY_EDGES_Q = ("MATCH (a:Facility)-[e:SUPPLIES]->(b:Facility) "
                  "RETURN a.facility_id AS a, b.facility_id AS b, e.annual_volume AS v")
SHIPPED_TOTALS_Q = "MATCH (c:Consignment)-[:SHIPPED_FROM]->(f:Facility) RETURN f.facility_id AS fid, count(c) AS n"
PLATFORMS_Q = ("MATCH (p:Platform)-[:PRODUCED_AT]->(f:Facility) "
               "RETURN f.facility_id AS fid, p.name AS name, p.archetype AS archetype")


@dataclass(frozen=True)
class Origin:
    node: Node
    kind: OriginKind
    key: str


@dataclass(frozen=True)
class FacilityIndex:
    by_fid: Mapping[str, Node]
    fid_by_id: Mapping[str, str]
    platforms: Mapping[str, tuple[tuple[str, str | None], ...]]


def _shares(frame: pd.DataFrame, totals: Mapping[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    for fid, n in zip(frame["fid"], frame["n"]):
        total = totals.get(str(fid), 0)
        if total > 0:
            out[str(fid)] = min(1.0, int(n) / total)
    return out


def _arc(parent: Node, child: Node, degree: int, via: str) -> Arc | None:
    if not (is_located(parent) and is_located(child)):
        return None
    return Arc(source=(parent.lon, parent.lat), target=(child.lon, child.lat), source_id=parent.id,
               target_id=child.id, hop=degree, rel=via)


def build_stages(origin: Origin, layers: Sequence[Sequence[Hit]], index: FacilityIndex) -> list[CascadeStage]:
    stages: list[CascadeStage] = []
    for layer in layers:
        hits: list[CascadeHit] = []
        arcs: list[Arc] = []
        for h in layer:
            node = index.by_fid.get(h.facility_id)
            if node is None:
                continue
            parent = (index.by_fid.get(h.parent) if h.parent else None) or origin.node
            hits.append(CascadeHit(node=with_status(node, "at_risk"), degree=h.degree, severity=h.severity,
                                   parent_id=parent.id, via=h.via))
            arc = _arc(parent, node, h.degree, h.via)
            if arc is not None:
                arcs.append(arc)
        if hits:
            mean = round(sum(x.severity for x in hits) / len(hits), 3)
            stages.append(CascadeStage(degree=layer[0].degree, hits=hits, arcs=arcs, count=len(hits),
                                       mean_severity=mean))
    return stages


def platform_exposure(origin: Origin, layers: Sequence[Sequence[Hit]], index: FacilityIndex) -> list[PlatformExposure]:
    best: dict[str, PlatformExposure] = {}
    affected = [(h.facility_id, h.severity) for layer in layers for h in layer]
    if origin.kind == "facility":
        affected.append((origin.key, 1.0))  # the lost facility's own platforms are fully exposed
    for fid, severity in affected:
        node = index.by_fid.get(fid)
        if node is None:
            continue
        for name, archetype in index.platforms.get(fid, ()):
            if name not in best or severity > best[name].severity:
                best[name] = PlatformExposure(name=name, archetype=archetype, severity=severity, facility_id=node.id)
    return sorted(best.values(), key=lambda p: (-p.severity, p.name))


class DeepCascade:
    def __init__(self, backend: TuringBackend) -> None:
        self.backend = backend
        self._lock = threading.Lock()
        self._cache: dict[tuple, object] = {}

    # ------------------------------------------------------------------ plumbing

    def session(self, ref: Ref, sw: Stopwatch | None = None) -> Session:
        return self.backend.session(ref, sw or Stopwatch(ENGINE))

    def _cached(self, s: Session, what: str, build: Callable[[], T]) -> T:
        key = (what, s.ref.branch, s.head())
        with self._lock:
            if key in self._cache:
                return self._cache[key]  # type: ignore[return-value]
        value = build()
        with self._lock:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = value
        return value

    # ------------------------------------------------------------------ reads (cached per branch head)

    def network(self, s: Session) -> SupplyNetwork:
        def build() -> SupplyNetwork:
            frame = s.q(SUPPLY_EDGES_Q)
            return SupplyNetwork.from_edges(
                (str(a), str(b), float(clean(v) or 0.0)) for a, b, v in zip(frame["a"], frame["b"], frame["v"]))
        return self._cached(s, "network", build)

    def _shipped_totals(self, s: Session) -> dict[str, int]:
        def build() -> dict[str, int]:
            frame = s.q(SHIPPED_TOTALS_Q)
            return {str(f): int(n) for f, n in zip(frame["fid"], frame["n"])}
        return self._cached(s, "shipped_totals", build)

    def facility_index(self, s: Session) -> FacilityIndex:
        def build() -> FacilityIndex:
            frame = s.q(f"MATCH (n:Facility) RETURN n, n.facility_id AS fid{s.project('n', NODE_PROPS)}")
            nodes = {n.id: n for n in s.nodes_from(frame, "n", label="Facility")}
            by_fid: dict[str, Node] = {}
            fid_by_id: dict[str, str] = {}
            for nid, fid in zip(frame["n"], frame["fid"]):
                node = nodes[str(nid)]
                by_fid[str(fid)] = node
                fid_by_id[node.id] = str(fid)
            platforms: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
            if "Platform" in s.labels:
                p = s.q(PLATFORMS_Q)
                for fid, name, archetype in zip(p["fid"], p["name"], p["archetype"]):
                    platforms[str(fid)].append((str(name), clean(archetype)))
            return FacilityIndex(by_fid, fid_by_id, {k: tuple(v) for k, v in platforms.items()})
        return self._cached(s, "facility_index", build)

    def catalog(self, s: Session) -> list[tuple[Node, OriginKind]]:
        def build() -> list[tuple[Node, OriginKind]]:
            out: list[tuple[Node, OriginKind]] = []
            for label in ("Chokepoint", "Port"):
                if label in s.labels:
                    frame = s.q(f"MATCH (n:{label}) RETURN n{s.project('n', NODE_PROPS)}")
                    out += [(n, ORIGIN_LABELS[label]) for n in s.nodes_from(frame, "n", label=label)]
            out += [(n, "facility") for n in self.facility_index(s).by_fid.values()]
            return out
        return self._cached(s, "catalog", build)

    # ------------------------------------------------------------------ origin + seeds

    def origin(self, s: Session, origin_id: str) -> Origin:
        nid = node_id_literal(origin_id)
        props = NODE_PROPS + tuple(KEY_PROP.values())
        frame = s.q(f"MATCH (n) WHERE n = {nid} RETURN n, labels(n) AS lbl{s.project('n', props)}")
        if frame.empty:
            raise NotFound(f"node {origin_id} not on {s.ref}")
        node = s.nodes_from(frame, "n", label_col="lbl")[0]
        kind = ORIGIN_LABELS.get(node.label)
        if kind is None:
            raise ValueError(f"a {node.label} cannot be a cascade origin: pick a chokepoint, port or facility")
        if not is_located(node):
            raise ValueError(f"{node.name} has no coordinates")
        key = clean(frame.iloc[0].get(f"n_{KEY_PROP[kind]}"))
        if key is None:
            raise ValueError(f"{node.name} has no {KEY_PROP[kind]}")
        return Origin(node=with_status(node, "lost"), kind=kind, key=str(key))

    @staticmethod
    def _origin_pattern(origin: Origin) -> str:
        return f"(o:{LABEL_OF[origin.kind]} {{{KEY_PROP[origin.kind]}: {string_literal(origin.key)}}})"

    def seeds(self, s: Session, origin: Origin) -> Seeds:
        if origin.kind == "facility":
            return Seeds({origin.key: 1.0}, degree=0, via="SUPPLIES")
        edge = SEED_EDGE[origin.kind]
        frame = s.q(f"MATCH {self._origin_pattern(origin)}<-[:{edge}]-(c:Consignment)-[:SHIPPED_FROM]->(f:Facility) "
                    "RETURN f.facility_id AS fid, count(DISTINCT c) AS n")
        return Seeds(_shares(frame, self._shipped_totals(s)), degree=1, via=edge)

    def seeds_by_origin(self, s: Session, kind: Literal["chokepoint", "port"]) -> dict[str, Seeds]:
        edge, label = SEED_EDGE[kind], LABEL_OF[kind]
        frame = s.q(f"MATCH (o:{label})<-[:{edge}]-(c:Consignment)-[:SHIPPED_FROM]->(f:Facility) "
                    "RETURN o, f.facility_id AS fid, count(DISTINCT c) AS n")
        totals = self._shipped_totals(s)
        frame = frame.assign(o=frame["o"].astype(str))
        return {str(oid): Seeds(_shares(group, totals), degree=1, via=edge) for oid, group in frame.groupby("o")}

    # ------------------------------------------------------------------ the speed proof

    def reach(self, s: Session, origin: Origin) -> ReachProbe:
        """One deep variable-length query, timed by TuringDB itself: unweighted reach up to MAX_DEGREE hops."""
        span = f"-[:SUPPLIES]->{{1,{MAX_DEGREE}}}(g:Facility)"
        if origin.kind == "facility":
            cypher = f"MATCH {self._origin_pattern(origin)}{span} RETURN count(DISTINCT g) AS reached"
        else:
            cypher = (f"MATCH {self._origin_pattern(origin)}<-[:{SEED_EDGE[origin.kind]}]-(c:Consignment)"
                      f"-[:SHIPPED_FROM]->(f:Facility){span} RETURN count(DISTINCT g) AS reached")
        frame = s.q(cypher)
        reached = int(frame["reached"].iloc[0]) if len(frame) else 0
        return ReachProbe(cypher=cypher, depth_limit=MAX_DEGREE, reached=reached, ms=s.sw.traces[-1].ms)

    # ------------------------------------------------------------------ the response

    def compute(self, ref: Ref, origin_id: str, min_severity: float = MIN_SEVERITY) -> CascadeResponse:
        sw = Stopwatch(ENGINE)
        s = self.session(ref, sw)
        origin = self.origin(s, origin_id)
        probe = self.reach(s, origin)
        layers = propagate(self.seeds(s, origin), self.network(s), min_severity)
        index = self.facility_index(s)
        stages = build_stages(origin, layers, index)
        hops = len(stages) + (1 if origin.kind != "facility" and stages else 0)
        return CascadeResponse(branch=str(ref), origin=origin.node, origin_kind=origin.kind, min_severity=min_severity,
                               stages=stages, max_degree=len(stages), graph_hops=hops,
                               total_affected=sum(st.count for st in stages), reach=probe,
                               platforms=platform_exposure(origin, layers, index), **sw.timed())
