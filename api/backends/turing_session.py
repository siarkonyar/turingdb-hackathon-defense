"""Thin per-request TuringDB session: a fresh SDK client checked out on one ref, with timing,
error mapping and schema-aware helpers (TuringDB errors on unknown labels/properties)."""

from __future__ import annotations

import re
from functools import cached_property
from typing import Iterable, Sequence

import pandas as pd
from turingdb import TuringDB

from api.models import Node
from api.nodes import make_node
from api.refs import Ref
from api.support import ApiError, BackendUnavailable, NotFound, Stopwatch

ID_CHUNK = 200  # ids per `WHERE n = a OR n = b ...` clause (3.0 rejects expressions nested > 256 deep;
#                 OR chains are id lookups, far faster than `n IN [...]`, which scans)
_NODE_ID = re.compile(r"^\d{1,12}$")
_HEAD = re.compile(r"\(HEAD\)$")


class QueryFailed(ApiError):
    status_code = 502


def node_id_literal(node_id: str) -> int:
    """Live node ids are TuringDB internal integer ids; anything else cannot exist (and is never interpolated)."""
    if not _NODE_ID.match(node_id):
        raise NotFound(f"node {node_id!r} does not exist (live ids are integers)")
    return int(node_id)


def string_literal(value: str) -> str:
    """Quote a string for Cypher. Quotes/backslashes are replaced: TuringDB string escaping is undocumented."""
    safe = value.replace("\\", "/").replace("'", "’").replace('"', "”")
    return f"'{safe}'"


def id_clauses(var: str, ids: Sequence[str]) -> list[str]:
    """`(var = 1 OR var = 2 ...)` clauses in chunks; ids are validated integers."""
    numbers = [node_id_literal(i) for i in ids]
    return ["(" + " OR ".join(f"{var} = {n}" for n in numbers[i:i + ID_CHUNK]) + ")"
            for i in range(0, len(numbers), ID_CHUNK)]


def strip_head(commit: str) -> str:
    return _HEAD.sub("", str(commit)).strip()


class Session:
    def __init__(self, host: str, graph: str, ref: Ref, sw: Stopwatch) -> None:
        self.ref, self.sw = ref, sw
        try:
            self.client = TuringDB(host=host)
            self.client.set_graph(graph)
            if ref.is_main:
                self.client.checkout(commit=ref.commit or "HEAD")
            else:
                self.client.checkout(change=int(ref.branch), commit=ref.commit or "HEAD")
        except Exception as exc:  # SDK raises TuringDBException or connection errors
            raise BackendUnavailable(f"cannot open {graph}@{ref} on {host}: {exc}") from exc

    def q(self, cypher: str) -> pd.DataFrame:
        try:
            frame = self.client.query(cypher)
        except Exception as exc:
            text = str(exc).strip()
            message = text.splitlines()[-1] if text else repr(exc)
            raise QueryFailed(f"TuringDB query failed ({message}): {cypher[:160]}") from exc
        self.sw.record(cypher, self.client.get_query_exec_time())
        return frame

    def refresh_schema(self) -> None:
        """Forget cached labels / property names (a write in this session may have created new ones)."""
        self.__dict__.pop("labels", None)
        self.__dict__.pop("property_types", None)

    @cached_property
    def labels(self) -> frozenset[str]:
        return frozenset(self.q("CALL db.labels()")["label"].astype(str))

    @cached_property
    def property_types(self) -> tuple[str, ...]:
        return tuple(self.q("CALL db.propertyTypes()")["propertyType"].astype(str))

    def has_props(self, names: Iterable[str]) -> list[str]:
        known = set(self.property_types)
        return [n for n in names if n in known]

    def head(self) -> str:
        return strip_head(self.q("CALL db.history()").iloc[0]["commit"])

    def history(self) -> list[tuple[str, int, int]]:
        frame = self.q("CALL db.history()")
        rows = [(strip_head(r.commit), int(r.nodeCount), int(r.edgeCount)) for r in frame.itertuples(index=False)]
        return list(reversed(rows))  # oldest first

    def project(self, var: str, props: Iterable[str]) -> str:
        cols = [f"{var}.`{p}` AS `{var}_{p}`" for p in self.has_props(props)]
        return ", " + ", ".join(cols) if cols else ""

    def nodes_from(self, frame: pd.DataFrame, var: str, label: str | None = None,
                   label_col: str | None = None) -> list[Node]:
        """Rows with a `<var>` id column and `<var>_<prop>` columns -> Nodes (first row per id wins)."""
        prefix = f"{var}_"
        prop_cols = [c for c in frame.columns if c.startswith(prefix)]
        seen: set[str] = set()
        out: list[Node] = []
        for row in frame.to_dict("records"):
            nid = str(row[var])
            if nid in seen:
                continue
            seen.add(nid)
            props = {c[len(prefix):]: row[c] for c in prop_cols}
            out.append(make_node(nid, first_label(row[label_col]) if label_col else (label or "Node"), props))
        return out


def first_label(value) -> str:
    """`labels(n)` is a list in TuringDB 3.0 (a string in 1.37); every theatre node has one label."""
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        items = list(value.tolist() if hasattr(value, "tolist") else value)
        return str(items[0]) if items else "Node"
    return str(value)
