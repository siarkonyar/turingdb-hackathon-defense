"""Read-only export of a source graph: every node label and edge type, with all properties."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from turingdb import TuringDB

from tdb import count


@dataclass(frozen=True)
class Table:
    """Rows of one label (column `_id`) or edge type (columns `_src`, `_dst`) plus properties."""

    name: str
    frame: pd.DataFrame
    types: dict[str, str]  # property -> TuringDB valueType

    @property
    def props(self) -> list[str]:
        return [c for c in self.frame.columns if not c.startswith("_")]


@dataclass(frozen=True)
class SourceGraph:
    name: str
    nodes: dict[str, Table]
    edges: dict[str, Table]

    def node_total(self) -> int:
        return sum(len(t.frame) for t in self.nodes.values())

    def edge_total(self) -> int:
        return sum(len(t.frame) for t in self.edges.values())


def _select(client: TuringDB, match: str, id_cols: dict[str, str], var: str,
            ptypes: dict[str, str]) -> tuple[pd.DataFrame, dict[str, str]]:
    names = list(ptypes)
    ret = [f"{expr} AS {alias}" for alias, expr in id_cols.items()]
    ret += [f"{var}.`{p}` AS c{i}" for i, p in enumerate(names)]
    frame = client.query(f"{match} RETURN {', '.join(ret)}")
    frame = frame.rename(columns={f"c{i}": p for i, p in enumerate(names)})
    present = [p for p in names if not frame[p].isna().all()]
    return frame[list(id_cols) + present], {p: ptypes[p] for p in present}


def export_graph(client: TuringDB, graph: str) -> SourceGraph:
    client.set_graph(graph)
    client.checkout()
    ptypes = dict(client.query("CALL db.propertyTypes()")[["propertyType", "valueType"]].itertuples(index=False))
    labels = client.query("CALL db.labels()")["label"].tolist()
    edge_types = client.query("CALL db.edgeTypes()")["edgeType"].tolist()

    nodes = {}
    for label in labels:
        frame, types = _select(client, f"MATCH (n:{label})", {"_id": "n"}, "n", ptypes)
        nodes[label] = Table(label, frame, types)
    edges = {}
    for etype in edge_types:
        frame, types = _select(client, f"MATCH (a)-[e:{etype}]->(b)", {"_src": "a", "_dst": "b"}, "e", ptypes)
        edges[etype] = Table(etype, frame, types)

    source = SourceGraph(graph, nodes, edges)
    _verify_totals(client, source)
    return source


def _verify_totals(client: TuringDB, source: SourceGraph) -> None:
    n_db = count(client, "MATCH (n) RETURN count(n)")
    e_db = count(client, "MATCH (a)-[e]->(b) RETURN count(e)")
    if source.node_total() != n_db or source.edge_total() != e_db:
        raise RuntimeError(f"{source.name}: exported {source.node_total()} nodes / {source.edge_total()} edges, "
                           f"graph has {n_db} / {e_db} (multi-label nodes?)")
    ids = pd.concat([t.frame["_id"] for t in source.nodes.values()])
    if ids.duplicated().any():
        raise RuntimeError(f"{source.name}: a node appears under more than one label")
