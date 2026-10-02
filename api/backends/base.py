"""The interface every backend implements; routes in api/main.py only talk to this."""

from __future__ import annotations

from typing import Protocol, Sequence

from api.models import (BranchesResponse, DiffResponse, MetaResponse, NeighboursResponse, NodesResponse,
                        ReportsResponse, SimulateResponse, TracksResponse)
from api.refs import BBox, Ref

NEIGHBOUR_CAP = 40  # nodes listed per relationship group in the drawer
NODE_KINDS = ("plant", "site", "supplier", "drone", "crime", "report", "part")


class Backend(Protocol):
    def meta(self) -> MetaResponse: ...

    def nodes(self, ref: Ref, kinds: Sequence[str], bbox: BBox | None) -> NodesResponse: ...

    def neighbours(self, node_id: str, ref: Ref) -> NeighboursResponse: ...

    def simulate(self, node_id: str, base: Ref) -> SimulateResponse: ...

    def discard(self, branch_id: str) -> None: ...

    def diff(self, a: Ref, b: Ref) -> DiffResponse: ...

    def branches(self) -> BranchesResponse: ...

    def reports(self, ref: Ref, until: str | None) -> ReportsResponse: ...

    def tracks(self, ref: Ref) -> TracksResponse: ...


STATUS_RANK = {None: 0, "at_risk": 1, "no_power": 2, "lost": 3}


def merge_status(old: str | None, new: str | None) -> str | None:
    """Statuses only escalate when strikes stack: no_power beats at_risk."""
    return new if STATUS_RANK.get(new, 0) > STATUS_RANK.get(old, 0) else old


def strike_label(names: Sequence[str]) -> str:
    return "Strike · " + " + ".join(names)
