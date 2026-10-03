"""Response shapes for /resilience/* (Dover exercises). Mirrored in ui/src/api/types.ts; contract in docs/api.md."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from api.models import CascadeResponse, Frozen, Node

ScenarioId = Literal["scenario:strait_closure", "scenario:kent_power", "scenario:london_loss"]


class ExerciseInfo(Frozen):
    scenario_id: ScenarioId
    title: str
    prompt: str
    kind: Literal["closure", "power_outage", "regional_loss"]
    hours: float


class ExercisesResponse(Frozen):
    exercises: list[ExerciseInfo]


class RunRequest(Frozen):
    scenario_id: ScenarioId


class RunStarted(Frozen):
    job_id: str
    scenario_id: ScenarioId


class AskRequest(Frozen):
    question: str = Field(min_length=2, max_length=400)


class AskResponse(Frozen):
    """Either a started run (the question matched an event in the graph) or a plain reply."""
    job_id: str | None = None
    scenario_id: ScenarioId | None = None
    title: str | None = None
    hours: float | None = None
    reply: str | None = None


class MetricsView(Frozen):
    essential_fulfilment: float
    overall_fulfilment: float
    demands_below_minimum: int
    capabilities_below_minimum: int
    capabilities_total: int
    cargo_scheduled_t: float
    cargo_on_time_t: float
    cargo_delayed_t: float
    cargo_unmet_t: float
    affected_facilities: int
    affected_at_end: int
    essential_recovery_h: float | None
    cost_units: float


class ConsumptionView(Frozen):
    stock_released_t: float
    reserves_drawn: int
    reserves_exhausted: int
    first_exhausted_h: float | None
    generators: int
    generator_fuel_t: float
    aircraft_sorties: int
    route_tonnes: dict[str, float]  # route name -> tonnes moved in the window
    provider_spare_t_day: float
    programme_people: float


class TimePointView(Frozen):
    hour: float
    essential: float
    overall: float
    capabilities_ok: int


class PathView(Frozen):
    names: list[str]
    via: list[str | None]  # dependency group into each step (None for the initial failure)
    severity: float


class BranchView(Frozen):
    branch: str
    role: Literal["disruption", "recovery"]
    plan_id: str | None
    parent: str
    verified: bool


class DisruptionView(Frozen):
    scenario_id: ScenarioId
    title: str
    hours: float
    branch: BranchView
    cascade: CascadeResponse
    metrics: MetricsView
    timeline: list[TimePointView]
    paths: list[PathView]
    unavailable: list[str]


class CandidateView(Frozen):
    plan_id: str
    title: str
    summary: str
    actions: int
    rank: int  # deterministic rank, 1 = best
    chosen: bool
    metrics: MetricsView
    consumption: ConsumptionView


class DecisionView(Frozen):
    mode: Literal["agent", "fallback"]
    plan_id: str
    rationale: str
    model: str | None
    calls: int
    reason: str | None = None


class GroupView(Frozen):
    key: str
    label: str
    actions: int
    ready_h: float
    capacity: str
    essential_gain: float  # percentage points
    overall_gain: float
    cargo_gain_t: float


class StatePoint(Frozen):
    node: Node
    state: Literal["lost", "relocated", "restored", "improved", "residual"]
    before: float
    after: float
    receiver_id: str | None = None


class LinkView(Frozen):
    kind: Literal["route", "power", "stock", "relocation", "export"]
    source: tuple[float, float]
    target: tuple[float, float]
    source_id: str
    target_id: str
    label: str
    group: str  # GroupView.key: the recovery step that introduces this link


class RecoveryView(Frozen):
    scenario_id: ScenarioId
    title: str
    hours: float
    disruption_branch: str
    branch: BranchView
    decision: DecisionView
    candidates: list[CandidateView]
    before: MetricsView
    after: MetricsView
    before_timeline: list[TimePointView]
    after_timeline: list[TimePointView]
    consumption: ConsumptionView
    groups: list[GroupView]
    limitations: list[str]
    counts: dict[str, int]
    services_relocated: int
    programmes_relocated: int
    points: list[StatePoint]
    links: list[LinkView]


class JobEventView(Frozen):
    id: int
    type: str
    data: dict = Field(default_factory=dict)


class JobView(Frozen):
    job_id: str
    status: str
    events: list[JobEventView]
    next: int
