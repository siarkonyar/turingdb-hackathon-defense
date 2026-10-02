"""Append-only builder for the fused graph, serialised as TuringDB-compatible JSONL
(Neo4j APOC export format: contiguous node ids from 0, one label per relationship)."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonScalar = str | int | float | bool

try:  # pandas is a turingdb dependency, but keep graph_model importable without it
    from pandas import NA as _PD_NA
except ImportError:  # pragma: no cover
    _PD_NA = object()


def clean_props(props: dict[str, Any]) -> dict[str, JsonScalar]:
    """Drop nulls/NaNs and coerce numpy/pandas scalars to plain Python values."""
    out: dict[str, JsonScalar] = {}
    for key, value in props.items():
        if value is None or value is _PD_NA:
            continue
        if hasattr(value, "item"):  # numpy scalar
            value = value.item()
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError(f"property {key!r} has unsupported type {type(value).__name__}")
        out[key] = value
    return out


@dataclass(frozen=True)
class NodeRecord:
    labels: tuple[str, ...]
    props: dict[str, JsonScalar]


@dataclass(frozen=True)
class EdgeRecord:
    start: int
    end: int
    edge_type: str
    props: dict[str, JsonScalar]


@dataclass
class GraphBuilder:
    """Single accumulation point for the build; the records themselves are immutable."""

    nodes: list[NodeRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)
    _keys: dict[tuple[str, str], int] = field(default_factory=dict)

    def add_node(self, labels: tuple[str, ...], props: dict[str, Any], key: tuple[str, str] | None = None) -> int:
        if not labels:
            raise ValueError("every node needs at least one label")
        node_id = len(self.nodes)
        if key is not None:
            if key in self._keys:
                raise ValueError(f"duplicate node key {key}")
            self._keys[key] = node_id
        self.nodes.append(NodeRecord(tuple(labels), clean_props(props)))
        return node_id

    def node_id(self, key: tuple[str, str]) -> int:
        return self._keys[key]

    def add_edge(self, start: int, end: int, edge_type: str, props: dict[str, Any] | None = None) -> None:
        if not (0 <= start < len(self.nodes) and 0 <= end < len(self.nodes)):
            raise ValueError(f"edge {edge_type} references unknown node ({start} -> {end})")
        self.edges.append(EdgeRecord(start, end, edge_type, clean_props(props or {})))

    def label_counts(self) -> Counter[str]:
        return Counter(label for n in self.nodes for label in n.labels)

    def edge_counts(self) -> Counter[str]:
        return Counter(e.edge_type for e in self.edges)

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for i, node in enumerate(self.nodes):
                fh.write(json.dumps({"type": "node", "id": str(i), "labels": list(node.labels),
                                     "properties": node.props}, ensure_ascii=False))
                fh.write("\n")
            for j, edge in enumerate(self.edges):
                fh.write(json.dumps({"type": "relationship", "id": str(j), "label": edge.edge_type,
                                     "start": {"id": str(edge.start)}, "end": {"id": str(edge.end)},
                                     "properties": edge.props}, ensure_ascii=False))
                fh.write("\n")
