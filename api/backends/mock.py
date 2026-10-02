"""Fixture-backed implementation of the API contract. Branches are in-memory overlays over main;
strikes run the same cascade (api/cascade.py) as the TuringDB backend."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Sequence

from api import cascade
from api.backends.base import NEIGHBOUR_CAP, merge_status, strike_label
from api.backends.mock_graph import MockGraph, Overlay, load_mock_graph
from api.diffing import diff_snapshots
from api.models import (Affected, Branch, BranchesResponse, DiffResponse, MetaResponse, NeighbourGroup,
                        NeighboursResponse, Node, NodesResponse, Report, ReportsResponse, SimulateResponse,
                        TracksResponse)
from api.nodes import with_status
from api.refs import BBox, Ref
from api.support import Conflict, NotFound, Stopwatch

ENGINE = "fixtures"
# rule -> which side of the stored edge is the dependent ("in": src depends on dst)
RULE_DIRECTION = {"POWERED_BY": "in", "SUPPLIED_BY": "in", "SOURCES_FROM": "in", "PATROLS": "in",
                  "DELIVERED_TO": "out"}


@dataclass(frozen=True)
class View:
    """What a ref sees: an optional overlay over main, cut at a commit."""

    overlay: Overlay | None
    commit_index: int


class MockDependencies:
    def __init__(self, view: View, mock: "MockBackend") -> None:
        self._view, self._mock = view, mock

    def dependents(self, label: str, ids: Sequence[str], rule: str) -> list[cascade.Dependency]:
        graph = self._mock.graph
        edges = graph.in_edges if RULE_DIRECTION[rule] == "in" else graph.out_edges
        deps = []
        for nid in ids:
            for e in edges.get(nid, ()):
                if e.rel == rule and self._mock.visible(e.other, self._view):
                    deps.append(cascade.Dependency(nid, self._mock.state(e.other, self._view), rule))
        return deps


class MockBackend:
    def __init__(self, fixtures_dir: Path) -> None:
        self.graph: MockGraph = load_mock_graph(fixtures_dir)
        self._lock = threading.Lock()
        self._branches: dict[str, Overlay] = {}
        for h in self.graph.hypotheses:
            overlay = Overlay(id=h["id"], kind="hypothesis", label=h["label"], description=h["description"],
                              confidence=h["confidence"])
            for node_id in h["strike"]:
                overlay, _ = self._strike(overlay, node_id)
            self._branches[overlay.id] = overlay

    # ------------------------------------------------------------------ views

    def _view(self, ref: Ref) -> View:
        index = self.graph.head_index
        if ref.commit is not None:
            match = [c.index for c in self.graph.commits if c.hash.startswith(ref.commit)]
            if not match:
                raise NotFound(f"unknown commit {ref.commit}")
            index = match[0]
        if ref.is_main:
            return View(None, index)
        with self._lock:
            overlay = self._branches.get(ref.branch)
        if overlay is None:
            raise NotFound(f"unknown branch {ref.branch}")
        return View(overlay, index)

    def visible(self, node_id: str, view: View) -> bool:
        if node_id not in self.graph.base:
            return False
        if view.overlay is not None and node_id in view.overlay.deleted:
            return False
        batch = self.graph.report_batch.get(node_id)
        return batch is None or batch <= view.commit_index

    def state(self, node_id: str, view: View) -> Node:
        node = self.graph.base[node_id]
        status = view.overlay.status.get(node_id) if view.overlay is not None else None
        return with_status(node, status) if status else node

    def _snapshot(self, view: View, kinds: Iterable[str] | None = None) -> dict[str, Node]:
        kinds = kinds or self.graph.by_kind.keys()
        return {n.id: self.state(n.id, view) for k in kinds for n in self.graph.by_kind.get(k, ())
                if self.visible(n.id, view)}

    # ------------------------------------------------------------------ reads

    def meta(self) -> MetaResponse:
        return MetaResponse(engine=ENGINE, graph="theatre (mock fixtures)",
                            layers=["plant", "site", "supplier", "drone", "crime", "cyber", "report"])

    def nodes(self, ref: Ref, kinds: Sequence[str], bbox: BBox | None) -> NodesResponse:
        sw = Stopwatch(ENGINE)
        view = self._view(ref)
        out = [self.state(n.id, view) for k in kinds for n in self.graph.by_kind.get(k, ())
               if self.visible(n.id, view) and (bbox is None or bbox.contains(n.lon, n.lat))]
        return NodesResponse(branch=str(ref), nodes=out, **sw.timed())

    def neighbours(self, node_id: str, ref: Ref) -> NeighboursResponse:
        sw = Stopwatch(ENGINE)
        view = self._view(ref)
        if not self.visible(node_id, view):
            raise NotFound(f"node {node_id} not on {ref}")
        groups = []
        for direction, edges in (("out", self.graph.out_edges), ("in", self.graph.in_edges)):
            by_rel: dict[str, list[Node]] = {}
            for e in edges.get(node_id, ()):
                if self.visible(e.other, view):
                    by_rel.setdefault(e.rel, []).append(self.state(e.other, view))
            for rel, nodes in sorted(by_rel.items()):
                ranked = sorted(nodes, key=lambda n: -n.importance)
                groups.append(NeighbourGroup(rel=rel, direction=direction, total=len(nodes),
                                             nodes=ranked[:NEIGHBOUR_CAP]))
        return NeighboursResponse(branch=str(ref), node=self.state(node_id, view),
                                  properties=dict(self.graph.props[node_id]), groups=groups, **sw.timed())

    def diff(self, a: Ref, b: Ref) -> DiffResponse:
        sw = Stopwatch(ENGINE)
        added, removed, changed = diff_snapshots(self._snapshot(self._view(a)), self._snapshot(self._view(b)))
        return DiffResponse(a=str(a), b=str(b), added=added, removed=removed, changed=changed, **sw.timed())

    def branches(self) -> BranchesResponse:
        sw = Stopwatch(ENGINE)
        main = Branch(id="main", kind="main", label="main", commits=list(self.graph.commits))
        with self._lock:
            others = sorted(self._branches.values(), key=lambda o: int(o.id))
        rest = [Branch(id=o.id, kind=o.kind, label=o.label, description=o.description, confidence=o.confidence)
                for o in others]
        return BranchesResponse(branches=[main, *rest], **sw.timed())

    def reports(self, ref: Ref, until: str | None) -> ReportsResponse:
        sw = Stopwatch(ENGINE)
        view = self._view(ref)
        out = []
        for node in self.graph.by_kind.get("report", ()):
            if not self.visible(node.id, view) or (until and (node.timestamp or "") > until):
                continue
            props, edges = self.graph.props[node.id], self.graph.out_edges.get(node.id, ())
            contradicts = [e.other for e in edges if e.rel == "CONTRADICTS"]
            out.append(Report(node=self.state(node.id, view), report_id=props["report_id"], text=props["text"],
                              claim=props.get("claim"), source_type=props.get("source_type"),
                              mentions=[e.other for e in edges if e.rel == "MENTIONS"],
                              contradicts=contradicts[0] if contradicts else None))
        out.sort(key=lambda r: r.node.timestamp or "")
        return ReportsResponse(branch=str(ref), until=until, reports=out, **sw.timed())

    def tracks(self, ref: Ref) -> TracksResponse:
        sw = Stopwatch(ENGINE)
        view = self._view(ref)
        tracks = [t for t in self.graph.tracks if self.visible(t.id, view)]
        return TracksResponse(branch=str(ref), tracks=tracks, **sw.timed())

    # ------------------------------------------------------------------ writes

    def _strike(self, overlay: Overlay, node_id: str) -> tuple[Overlay, tuple[Node, list[Affected]]]:
        view = View(overlay, self.graph.head_index)
        if not self.visible(node_id, view):
            raise NotFound(f"node {node_id} is not present on branch {overlay.id}")
        struck = self.state(node_id, view)
        affected = cascade.walk(struck, MockDependencies(view, self))
        deleted = overlay.deleted | {node_id}
        unpowered = {fid for fid in cascade.powered_ids(affected)
                     if not any(e.rel == "POWERED_BY" and e.other not in deleted
                                for e in self.graph.out_edges.get(fid, ()))}
        affected = cascade.apply_statuses(affected, unpowered)
        status = dict(overlay.status)
        for a in affected:
            status[a.node.id] = merge_status(status.get(a.node.id), a.node.status)
        status.pop(node_id, None)
        updated = replace(overlay, deleted=frozenset(deleted), status=MappingProxyType(status),
                          struck_names=overlay.struck_names + (struck.name,))
        return updated, (with_status(struck, "lost"), affected)

    def simulate(self, node_id: str, base: Ref) -> SimulateResponse:
        sw = Stopwatch(ENGINE)
        with self._lock:
            if base.is_main:
                next_id = str(max((int(k) for k in self._branches), default=0) + 1)
                overlay = Overlay(id=next_id, kind="strike", label="")
            else:
                overlay = self._branches.get(base.branch)
                if overlay is None:
                    raise NotFound(f"unknown branch {base.branch}")
                if overlay.kind != "strike":
                    raise Conflict("hypothesis branches are read-only; simulate from main or a strike branch")
            overlay, (struck, affected) = self._strike(overlay, node_id)
            overlay = replace(overlay, label=strike_label(overlay.struck_names))
            self._branches[overlay.id] = overlay
        view = View(overlay, self.graph.head_index)
        lost = [struck] + [a.node for a in affected if a.node.status == "no_power"]
        branch_nodes = [self.state(nid, view) for nid in overlay.status]
        return SimulateResponse(branch=overlay.id, base_branch=str(base), struck=struck, affected=affected,
                                lost=lost, arcs=cascade.build_arcs(struck, affected),
                                kpis=cascade.kpis(branch_nodes), **sw.timed())

    def discard(self, branch_id: str) -> None:
        with self._lock:
            overlay = self._branches.get(branch_id)
            if overlay is None:
                raise NotFound(f"unknown branch {branch_id}")
            if overlay.kind != "strike":
                raise Conflict("only strike branches can be discarded")
            del self._branches[branch_id]
