"""Live implementation of the API contract over a TuringDB graph (default `theatre`).

Branches are TuringDB changes. A change describes itself with a marker node:
    (:Hypothesis {name, confidence, description})   intelligence hypothesis (made by the fusion agent)
    (:Strike {struck_id, name, created})             strike simulation (made by POST /simulate)
Node state on a branch: deleted nodes are lost; `ops_status` ('at_risk' | 'no_power') marks impact.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Sequence

from api import cascade
from api.backends.base import NEIGHBOUR_CAP, merge_status, strike_label
from api.backends.turing_session import Session, id_clauses, node_id_literal, string_literal
from api.diffing import diff_snapshots
from api.models import (Branch, BranchesResponse, Commit, DiffResponse, MetaResponse, NeighbourGroup,
                        NeighboursResponse, Node, NodesResponse, Report, ReportsResponse, SimulateResponse,
                        Track, TracksResponse)
from api.nodes import clean, with_status
from api.refs import BBox, Ref
from api.support import Conflict, NotFound, Stopwatch

log = logging.getLogger("opsmap.turing")
ENGINE = "turingdb"
NODE_PROPS = ("name", "type", "latitude", "longitude", "source", "timestamp", "synthetic", "geo_synthetic",
              "ops_status", "primary_fuel", "capacity_mw", "confidence")
REPORT_PROPS = NODE_PROPS + ("report_id", "text", "claim", "source_type")
STATUS_PROPS = ("name", "latitude", "longitude", "ops_status")
# kind -> (labels the pattern needs, MATCH pattern binding n, extra WHERE)
KIND_QUERIES: dict[str, tuple[tuple[str, ...], str, str | None]] = {
    "plant": (("PowerPlant",), "MATCH (n:PowerPlant)", None),
    "site": (("Site",), "MATCH (n:Site)", None),
    "supplier": (("Supplier",), "MATCH (n:Supplier)", "n.source = 'supply_chain'"),
    "drone": (("Drone",), "MATCH (n:Drone)", None),
    "crime": (("Crime", "Location", "Site"), "MATCH (n:Crime)-[:OCCURRED_AT]->(l:Location)-[:NEAR]->(s:Site)", None),
    "report": (("Report",), "MATCH (n:Report)", None),
    "part": (("Part",), "MATCH (n:Part)", None),
}
SNAPSHOT_KINDS = ("plant", "site", "supplier", "drone", "report", "part")
TRACK_EVERY = 6  # keep every 6th drone reading
CACHE_LIMIT = 48
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TuringDependencies:
    """cascade.DependencySource answered with one TuringDB query per (rule, id chunk)."""

    def __init__(self, session: Session) -> None:
        self.s = session

    def dependents(self, label: str, ids: Sequence[str], rule: str) -> list[cascade.Dependency]:
        # The struck ids come first and carry no label: TuringDB then starts from an id lookup
        # (~0.05 ms) instead of scanning the labelled side (~15 ms). `ids` all carry `label` already.
        if not _LABEL.match(label) or not _LABEL.match(rule):
            raise ValueError(f"unsafe label/rule {label!r}/{rule!r}")
        if rule == "DELIVERED_TO":
            pattern = "MATCH (x)<-[:FOR_PART]-(po)-[:DELIVERED_TO]->(d)"
        else:
            pattern = f"MATCH (x)<-[:{rule}]-(d)"
        deps: list[cascade.Dependency] = []
        for clause in id_clauses("x", ids):
            frame = self.s.q(f"{pattern} WHERE {clause} RETURN x, d, labels(d) AS lbl{self.s.project('d', NODE_PROPS)}")
            frame = frame.drop_duplicates(subset=["d"])
            parents = [str(x) for x in frame["x"]]
            for parent, child in zip(parents, self.s.nodes_from(frame, "d", label_col="lbl")):
                deps.append(cascade.Dependency(parent, child, rule))
        return deps


class TuringBackend:
    def __init__(self, host: str, graph: str) -> None:
        self.host, self.graph = host, graph
        self._write_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: dict[tuple, object] = {}
        self._loaded = False

    # ------------------------------------------------------------------ plumbing

    def _open(self, ref: Ref, sw: Stopwatch) -> Session:
        return Session(self.host, self.graph, ref, sw)

    def _session(self, ref: Ref, sw: Stopwatch) -> Session:
        if not self._loaded:
            Session(self.host, "default", Ref("main"), sw).client.load_graph(self.graph, raise_if_loaded=False)
            self._loaded = True
        if not ref.is_main and ref.branch not in self._change_ids(sw):
            raise NotFound(f"unknown branch {ref.branch}")
        return self._open(ref, sw)

    def _change_ids(self, sw: Stopwatch) -> set[str]:
        frame = self._open(Ref("main"), sw).q("CHANGE LIST")
        return {str(c) for c in frame.iloc[:, 0]} if len(frame) else set()

    def _cached(self, key: tuple, build):
        with self._cache_lock:
            if key in self._cache:
                return self._cache[key]
        value = build()
        with self._cache_lock:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = value
        return value

    def _version(self, s: Session) -> str:
        return s.ref.commit or s.head()

    def _exposure(self, s: Session) -> dict[str, int]:
        def build() -> dict[str, int]:
            if not {"Attack", "AssetType"} <= s.labels:
                return {}
            per_type = Counter(s.q("MATCH (a:Attack)-[:TARGETS]->(t:AssetType) RETURN a, t.asset_type_id AS type_id")["type_id"])
            out: Counter[str] = Counter()
            for label in ("Site", "Supplier"):
                if label in s.labels:
                    frame = s.q(f"MATCH (n:{label})-[:RUNS]->(t:AssetType) RETURN n, t.asset_type_id AS type_id")
                    for nid, t in frame.itertuples(index=False):
                        out[str(nid)] += per_type.get(t, 0)
            return dict(out)
        return self._cached(("exposure", self.graph), build)

    def _kind_nodes(self, s: Session, kind: str) -> tuple[Node, ...]:
        def build() -> tuple[Node, ...]:
            needs, pattern, where = KIND_QUERIES[kind]
            if not set(needs) <= s.labels:
                return ()
            clause = f" WHERE {where}" if where else ""
            frame = s.q(f"{pattern}{clause} RETURN n{s.project('n', NODE_PROPS)}")
            nodes = s.nodes_from(frame, "n", label=needs[0])
            if kind in ("site", "supplier"):
                exposure = self._exposure(s)
                nodes = [n.model_copy(update={"exposure": exposure.get(n.id)}) for n in nodes]
            return tuple(nodes)
        return self._cached(("kind", s.ref.branch, self._version(s), kind), build)

    def _snapshot(self, s: Session) -> dict[str, Node]:
        return {n.id: n for kind in SNAPSHOT_KINDS for n in self._kind_nodes(s, kind)}

    def _node(self, s: Session, node_id: str) -> Node:
        nid = node_id_literal(node_id)
        frame = s.q(f"MATCH (n) WHERE n = {nid} RETURN n, labels(n) AS lbl{s.project('n', NODE_PROPS)}")
        if frame.empty:
            raise NotFound(f"node {node_id} not on {s.ref}")
        return s.nodes_from(frame, "n", label_col="lbl")[0]

    # ------------------------------------------------------------------ reads

    def meta(self) -> MetaResponse:
        return MetaResponse(engine=ENGINE, graph=self.graph,
                            layers=["plant", "site", "supplier", "drone", "crime", "cyber", "report"])

    def nodes(self, ref: Ref, kinds: Sequence[str], bbox: BBox | None) -> NodesResponse:
        sw = Stopwatch(ENGINE)
        s = self._session(ref, sw)
        out = [n for k in kinds for n in self._kind_nodes(s, k) if bbox is None or bbox.contains(n.lon, n.lat)]
        return NodesResponse(branch=str(ref), nodes=out, **sw.timed())

    def neighbours(self, node_id: str, ref: Ref) -> NeighboursResponse:
        sw = Stopwatch(ENGINE)
        s = self._session(ref, sw)
        node = self._node(s, node_id)
        nid = int(node.id)
        cols = ", ".join(f"n.`{p}` AS `{p}`" for p in s.property_types)
        props = {k: clean(v) for k, v in s.q(f"MATCH (n) WHERE n = {nid} RETURN {cols}").iloc[0].items()}
        groups = []
        for direction, pattern in (("out", "(n)-[e]->(m)"), ("in", "(n)<-[e]-(m)")):
            frame = s.q(f"MATCH {pattern} WHERE n = {nid} RETURN edgeType(e) AS rel, m, labels(m) AS lbl"
                        f"{s.project('m', NODE_PROPS)}")
            for rel, part in sorted(frame.groupby("rel"), key=lambda kv: str(kv[0])):
                nodes = sorted(s.nodes_from(part, "m", label_col="lbl"), key=lambda n: -n.importance)
                groups.append(NeighbourGroup(rel=str(rel), direction=direction, total=len(nodes),
                                             nodes=nodes[:NEIGHBOUR_CAP]))
        return NeighboursResponse(branch=str(ref), node=node, groups=groups,
                                  properties={k: v for k, v in props.items() if v is not None}, **sw.timed())

    def diff(self, a: Ref, b: Ref) -> DiffResponse:
        sw = Stopwatch(ENGINE)
        snap_a = self._snapshot(self._session(a, sw))
        snap_b = self._snapshot(self._session(b, sw))
        added, removed, changed = diff_snapshots(snap_a, snap_b)
        return DiffResponse(a=str(a), b=str(b), added=added, removed=removed, changed=changed, **sw.timed())

    def _commit_time(self, commit: str, sw: Stopwatch) -> str | None:
        def build() -> str | None:
            s = self._open(Ref("main", commit), sw)
            if "Report" not in s.labels:
                return None
            stamps = [t for t in s.q("MATCH (r:Report) RETURN r.timestamp AS t")["t"] if clean(t)]
            return max(stamps) if stamps else None
        return self._cached(("commit_time", commit), build)

    def _describe_change(self, change_id: str, sw: Stopwatch) -> Branch:
        s = self._open(Ref(change_id), sw)
        if "Hypothesis" in s.labels:
            frame = s.q(f"MATCH (h:Hypothesis) RETURN h{s.project('h', ('name', 'confidence', 'description'))}")
            row = frame.to_dict("records")[0] if len(frame) else {}
            confidence = clean(row.get("h_confidence"))
            return Branch(id=change_id, kind="hypothesis", label=clean(row.get("h_name")) or f"Hypothesis {change_id}",
                          description=clean(row.get("h_description")),
                          confidence=float(confidence) if confidence is not None else None)
        if "Strike" in s.labels:
            names = [str(n) for n in s.q("MATCH (k:Strike) RETURN k.name AS name")["name"]]
            return Branch(id=change_id, kind="strike", label=strike_label(names))
        if "AgentBranch" in s.labels:  # branches built by the LLM agents (threat / defence / scenario)
            frame = s.q(f"MATCH (m:AgentBranch) RETURN m{s.project('m', ('role', 'label', 'parent'))}")
            row = frame.to_dict("records")[0] if len(frame) else {}
            role = clean(row.get("m_role")) or "change"
            kind = role if role in ("threat", "defence", "scenario") else "change"
            label = clean(row.get("m_label")) or f"{role.title()} {change_id}"
            parent = clean(row.get("m_parent"))
            return Branch(id=change_id, kind=kind, label=label,
                          description=f"parent: {parent}" if parent and parent != "main" else None)
        return Branch(id=change_id, kind="change", label=f"Change {change_id}")

    def branches(self) -> BranchesResponse:
        sw = Stopwatch(ENGINE)
        main = self._session(Ref("main"), sw)
        commits = [Commit(hash=h, index=i, node_delta=n, edge_delta=e, time=self._commit_time(h, sw))
                   for i, (h, n, e) in enumerate(main.history())]
        others = []
        for cid in sorted(self._change_ids(sw), key=int):
            try:
                others.append(self._describe_change(cid, sw))
            except Exception as exc:  # a change on another graph, or one deleted meanwhile
                log.warning("skipping change %s: %s", cid, exc)
        branches = [Branch(id="main", kind="main", label="main", commits=commits), *others]
        return BranchesResponse(branches=branches, **sw.timed())

    def reports(self, ref: Ref, until: str | None) -> ReportsResponse:
        sw = Stopwatch(ENGINE)
        s = self._session(ref, sw)
        if "Report" not in s.labels:
            return ReportsResponse(branch=str(ref), until=until, reports=[], **sw.timed())
        frame = s.q(f"MATCH (r:Report) RETURN r{s.project('r', REPORT_PROPS)}")
        links = s.q("MATCH (r:Report)-[e]->(m) RETURN r, edgeType(e) AS rel, m")
        mentions: dict[str, list[str]] = {}
        contradicts: dict[str, str] = {}
        for r, rel, m in links.itertuples(index=False):
            if rel == "MENTIONS":
                mentions.setdefault(str(r), []).append(str(m))
            elif rel == "CONTRADICTS":
                contradicts[str(r)] = str(m)
        out = []
        for node, row in zip(s.nodes_from(frame, "r", label="Report"), frame.to_dict("records")):
            if until and (node.timestamp or "") > until:
                continue
            out.append(Report(node=node, report_id=str(clean(row.get("r_report_id")) or node.id),
                              text=str(clean(row.get("r_text")) or ""), claim=clean(row.get("r_claim")),
                              source_type=clean(row.get("r_source_type")), mentions=mentions.get(node.id, []),
                              contradicts=contradicts.get(node.id)))
        out.sort(key=lambda r: r.node.timestamp or "")
        return ReportsResponse(branch=str(ref), until=until, reports=out, **sw.timed())

    def tracks(self, ref: Ref) -> TracksResponse:
        sw = Stopwatch(ENGINE)
        s = self._session(ref, sw)

        def build() -> list[Track]:
            if not {"Reading", "Drone"} <= s.labels or "ts_epoch" not in s.property_types:
                return []
            frame = s.q("MATCH (r:Reading)-[:OF_DRONE]->(d:Drone) RETURN d, d.name AS name, r.ts_epoch AS t, "
                        "r.latitude AS lat, r.longitude AS lon").dropna().sort_values(["d", "t"])
            tracks = []
            for did, part in frame.groupby("d"):
                part = part.iloc[::TRACK_EVERY]
                tracks.append(Track(id=str(did), name=str(part["name"].iloc[0]),
                                    path=list(zip(part["lon"].astype(float), part["lat"].astype(float))),
                                    timestamps=[int(t) for t in part["t"]]))
            return tracks
        tracks = self._cached(("tracks", ref.branch, self._version(s)), build)
        return TracksResponse(branch=str(ref), tracks=tracks, **sw.timed())

    # ------------------------------------------------------------------ writes

    def _strike_branch(self, base: Ref, sw: Stopwatch) -> tuple[Session, bool]:
        if base.commit is not None:
            raise ValueError("simulate takes a branch head, not a commit")
        if base.is_main:
            change = self._session(Ref("main"), sw).client.new_change()
            return self._open(Ref(str(change)), sw), True
        session = self._session(base, sw)
        if self._describe_change(base.branch, sw).kind != "strike":
            raise Conflict("only main or a strike branch can be struck; hypothesis branches are read-only")
        return session, False

    def simulate(self, node_id: str, base: Ref) -> SimulateResponse:
        sw = Stopwatch(ENGINE)
        with self._write_lock:
            s, created = self._strike_branch(base, sw)
            try:
                return self._run_strike(s, node_id, base, sw, fresh=created)
            except Exception:
                if created:
                    self._drop_change(s)
                raise

    def _drop_change(self, s: Session) -> None:
        try:
            s.q("CHANGE DELETE")
        except Exception as exc:
            log.error("could not delete change %s after a failed strike: %s", s.ref.branch, exc)

    def _run_strike(self, s: Session, node_id: str, base: Ref, sw: Stopwatch, fresh: bool,
                    marker: bool = True) -> SimulateResponse:
        struck = self._node(s, node_id)
        affected = cascade.walk(struck, TuringDependencies(s))
        previous = {a.node.id: a.node.status for a in affected}
        if marker:
            s.q(f"CREATE (:Strike {{struck_id: '{int(struck.id)}', name: {string_literal(struck.name)}, "
                f"created: '{_now()}'}})")
        s.q(f"MATCH (n) WHERE n = {int(struck.id)} DELETE n")
        s.q("COMMIT")
        powered = cascade.powered_ids(affected)
        still_fed: set[str] = set()
        for clause in id_clauses("f", powered):
            still_fed |= {str(f) for f in s.q(f"MATCH (f)-[:POWERED_BY]->(p) WHERE {clause} RETURN f")["f"]}
        affected = cascade.apply_statuses(affected, set(powered) - still_fed)
        final = {a.node.id: merge_status(previous[a.node.id], a.node.status) for a in affected}
        affected = [a.model_copy(update={"node": with_status(a.node, final[a.node.id])}) for a in affected]
        for status in ("at_risk", "no_power"):
            for clause in id_clauses("n", [i for i, st in final.items() if st == status]):
                s.q(f"MATCH (n) WHERE {clause} SET n.ops_status = '{status}'")
        s.q("COMMIT")
        lost = [with_status(struck, "lost")] + [a.node for a in affected if a.node.status == "no_power"]
        # a fresh branch holds exactly this strike's statuses; a stacked one needs a branch-wide read
        branch_nodes = [a.node for a in affected] if fresh else self._status_nodes(s.ref, sw)
        return SimulateResponse(branch=s.ref.branch, base_branch=str(base), struck=lost[0], affected=affected,
                                lost=lost, arcs=cascade.build_arcs(struck, affected),
                                kpis=cascade.kpis(branch_nodes), **sw.timed())

    def _status_nodes(self, ref: Ref, sw: Stopwatch) -> list[Node]:
        """Every node carrying ops_status on the branch (fresh session: the property may be new)."""
        s = self._open(ref, sw)
        if "ops_status" not in s.property_types:
            return []
        nodes: list[Node] = []
        for status in ("at_risk", "no_power"):
            frame = s.q(f"MATCH (n) WHERE n.ops_status = '{status}' RETURN n, labels(n) AS lbl"
                        f"{s.project('n', STATUS_PROPS)}")
            nodes += s.nodes_from(frame, "n", label_col="lbl")
        return nodes

    def create_hypothesis(self, name: str, confidence: float, description: str,
                          lost: Sequence[str] = (), at_risk: Sequence[str] = ()) -> str:
        """Open a hypothesis branch: a (:Hypothesis) marker, then each `lost` node struck with its
        cascade and each `at_risk` node flagged. Returns the change id. Used by api/seed_hypotheses.py."""
        sw = Stopwatch(ENGINE)
        with self._write_lock:
            change = str(self._session(Ref("main"), sw).client.new_change())
            s = self._open(Ref(change), sw)
            try:
                s.q(f"CREATE (:Hypothesis {{name: {string_literal(name)}, confidence: {float(confidence)}, "
                    f"description: {string_literal(description)}}})")
                s.q("COMMIT")
                for i, node_id in enumerate(lost):
                    self._run_strike(s, node_id, Ref("main"), sw, fresh=i == 0, marker=False)
                for clause in id_clauses("n", list(at_risk)):
                    s.q(f"MATCH (n) WHERE {clause} SET n.ops_status = 'at_risk'")
                s.q("COMMIT")
            except Exception:
                self._drop_change(s)
                raise
        return change

    DISCARDABLE = ("strike", "threat", "defence", "scenario")

    def discard(self, branch_id: str) -> None:
        sw = Stopwatch(ENGINE)
        with self._write_lock:
            s = self._session(Ref(branch_id), sw)
            if self._describe_change(branch_id, sw).kind not in self.DISCARDABLE:
                raise Conflict("only strike and agent branches can be discarded; hypotheses are read-only")
            s.q("CHANGE DELETE")
