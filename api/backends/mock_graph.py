"""Immutable in-memory index over the mock fixture (api/mock/fixtures/theatre_mock.json.gz)."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from api.models import Commit, Node, Track
from api.nodes import make_node
from api.support import BackendUnavailable

FIXTURE_NAME = "theatre_mock.json.gz"


@dataclass(frozen=True)
class EdgeRef:
    other: str  # node id at the other end
    rel: str
    props: Mapping[str, Any]


@dataclass(frozen=True)
class Overlay:
    """A branch as a delta over main HEAD: deleted node ids plus per-node status."""

    id: str
    kind: str  # hypothesis | strike
    label: str
    description: str | None = None
    confidence: float | None = None
    deleted: frozenset[str] = frozenset()
    status: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    struck_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class MockGraph:
    props: Mapping[str, Mapping[str, Any]]
    base: Mapping[str, Node]
    by_kind: Mapping[str, tuple[Node, ...]]
    out_edges: Mapping[str, tuple[EdgeRef, ...]]
    in_edges: Mapping[str, tuple[EdgeRef, ...]]
    report_batch: Mapping[str, int]
    commits: tuple[Commit, ...]
    hypotheses: tuple[Mapping[str, Any], ...]
    tracks: tuple[Track, ...]

    @property
    def head_index(self) -> int:
        return len(self.commits) - 1


def _commits(raw: list[dict[str, Any]], reports: list[Node], batch: Mapping[str, int]) -> tuple[Commit, ...]:
    out = []
    for c in raw:
        stamps = [r.timestamp for r in reports if r.timestamp and batch[r.id] <= c["index"]]
        out.append(Commit(hash=c["hash"], index=c["index"], node_delta=c["node_delta"],
                          edge_delta=c["edge_delta"], time=max(stamps) if stamps else None))
    return tuple(out)


def load_mock_graph(fixtures_dir: Path) -> MockGraph:
    path = fixtures_dir / FIXTURE_NAME
    if not path.exists():
        raise BackendUnavailable(f"mock fixture {path} missing; run `uv run python -m api.mock.generate`")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)

    props = {n["id"]: MappingProxyType(n["props"]) for n in data["nodes"]}
    base = {n["id"]: make_node(n["id"], n["label"], n["props"]) for n in data["nodes"]}
    by_kind: dict[str, list[Node]] = defaultdict(list)
    for node in base.values():
        by_kind[node.kind].append(node)

    out_edges: dict[str, list[EdgeRef]] = defaultdict(list)
    in_edges: dict[str, list[EdgeRef]] = defaultdict(list)
    for src, dst, rel, eprops in data["edges"]:
        frozen = MappingProxyType(eprops or {})
        out_edges[src].append(EdgeRef(dst, rel, frozen))
        in_edges[dst].append(EdgeRef(src, rel, frozen))

    batch = {nid: int(p["batch"]) for nid, p in props.items() if base[nid].kind == "report"}
    tracks = tuple(Track(id=t["id"], name=t["name"], path=[tuple(p) for p in t["path"]],
                         timestamps=t["timestamps"]) for t in data["tracks"])
    return MockGraph(
        props=MappingProxyType(props),
        base=MappingProxyType(base),
        by_kind=MappingProxyType({k: tuple(v) for k, v in by_kind.items()}),
        out_edges=MappingProxyType({k: tuple(v) for k, v in out_edges.items()}),
        in_edges=MappingProxyType({k: tuple(v) for k, v in in_edges.items()}),
        report_batch=MappingProxyType(batch),
        commits=_commits(data["commits"], list(by_kind["report"]), batch),
        hypotheses=tuple(MappingProxyType(h) for h in data["hypotheses"]),
        tracks=tracks,
    )
