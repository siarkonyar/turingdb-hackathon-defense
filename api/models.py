"""Response/request models shared by every backend. This file *is* the API contract
(see docs/api.md); both the mock and the TuringDB backend must return exactly these shapes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["plant", "site", "supplier", "drone", "crime", "report", "part", "other"]
Status = Literal["at_risk", "lost", "no_power"]
BranchKind = Literal["main", "hypothesis", "strike", "change"]
Engine = Literal["turingdb", "fixtures"]

LOCATED_KINDS: tuple[str, ...] = ("plant", "site", "supplier", "drone", "crime", "report")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Node(Frozen):
    id: str
    kind: Kind
    label: str  # TuringDB node label, e.g. PowerPlant
    name: str
    lat: float | None = None
    lon: float | None = None
    source: str | None = None
    timestamp: str | None = None  # ISO-8601 UTC
    synthetic: bool | None = None
    status: Status | None = None  # state on the requested branch (None = nominal)
    importance: float = 0.5  # 0..1, drives glyph size
    fuel: str | None = None  # plants only
    capacity_mw: float | None = None  # plants only
    exposure: int | None = None  # sites/suppliers: attack scenarios targeting systems the asset runs
    confidence: float | None = None  # reports only


class QueryTrace(Frozen):
    cypher: str
    ms: float | None  # server-side execution time reported by TuringDB (None for fixtures)


class Timed(Frozen):
    engine: Engine
    latency_ms: float  # TuringDB server time summed over `queries` (fixtures: in-process time)
    roundtrip_ms: float  # wall-clock time spent in the backend call
    queries: list[QueryTrace] = Field(default_factory=list)


class NodesResponse(Timed):
    branch: str
    nodes: list[Node]


class NeighbourGroup(Frozen):
    rel: str  # edge type, e.g. POWERED_BY
    direction: Literal["out", "in"]
    total: int  # may exceed len(nodes) for high-degree nodes
    nodes: list[Node]


class NeighboursResponse(Timed):
    branch: str
    node: Node
    properties: dict[str, Any]
    groups: list[NeighbourGroup]


class SimulateRequest(Frozen):
    node_id: str = Field(min_length=1, max_length=64)
    base_branch: str = Field(default="main", min_length=1, max_length=64)


class Affected(Frozen):
    node: Node
    hop: int
    via: str  # dependency edge that carried the impact, e.g. POWERED_BY
    parent_id: str


class Arc(Frozen):
    source: tuple[float, float]  # [lon, lat]
    target: tuple[float, float]
    source_id: str
    target_id: str
    hop: int
    rel: str


class Kpis(Frozen):
    assets_at_risk: int
    sites_without_power: int
    suppliers_without_power: int
    parts_affected: int


class SimulateResponse(Timed):
    branch: str
    base_branch: str
    struck: Node
    affected: list[Affected]
    lost: list[Node]
    arcs: list[Arc]
    kpis: Kpis  # branch-wide: strikes stack on a strike branch


class Commit(Frozen):
    hash: str
    index: int  # 0 = oldest
    node_delta: int
    edge_delta: int
    time: str | None = None  # latest report timestamp visible at this commit, if any


class Branch(Frozen):
    id: str  # "main" or a TuringDB change id
    kind: BranchKind
    label: str
    description: str | None = None
    confidence: float | None = None
    commits: list[Commit] = Field(default_factory=list)


class BranchesResponse(Timed):
    branches: list[Branch]


class Change(Frozen):
    node: Node  # state on b
    fields: dict[str, tuple[Any, Any]]  # field -> (value on a, value on b)


class DiffResponse(Timed):
    a: str
    b: str
    added: list[Node]
    removed: list[Node]
    changed: list[Change]


class Report(Frozen):
    node: Node
    report_id: str
    text: str
    claim: str | None = None
    source_type: str | None = None
    mentions: list[str]  # node ids
    contradicts: str | None = None  # node id of the disputed report


class ReportsResponse(Timed):
    branch: str
    until: str | None
    reports: list[Report]


class Track(Frozen):
    id: str
    name: str
    path: list[tuple[float, float]]  # [lon, lat]
    timestamps: list[int]  # epoch seconds, same length as path


class TracksResponse(Timed):
    branch: str
    tracks: list[Track]


class MetaResponse(Frozen):
    engine: Engine
    graph: str
    layers: list[str]
