"""Compare two node snapshots (id -> Node) taken on two refs."""

from __future__ import annotations

from typing import Mapping

from api.models import Change, Node

DIFF_FIELDS = ("name", "status", "lat", "lon", "confidence", "timestamp", "capacity_mw")


def diff_snapshots(a: Mapping[str, Node], b: Mapping[str, Node]) -> tuple[list[Node], list[Node], list[Change]]:
    added = [b[i] for i in sorted(b.keys() - a.keys())]
    removed = [a[i] for i in sorted(a.keys() - b.keys())]
    changed: list[Change] = []
    for i in sorted(a.keys() & b.keys()):
        before, after = a[i], b[i]
        fields = {f: (getattr(before, f), getattr(after, f)) for f in DIFF_FIELDS
                  if getattr(before, f) != getattr(after, f)}
        if fields:
            changed.append(Change(node=after, fields=fields))
    return added, removed, changed
