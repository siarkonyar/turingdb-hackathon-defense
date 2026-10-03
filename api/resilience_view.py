"""Shape measured resilience outcomes (agents/resilience) into API responses, including a Plan A-compatible
CascadeResponse whose degrees are DEPENDS_ON distances from several simultaneous initial failures."""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from agents.resilience.agent import Decision
from agents.resilience.candidates import CandidateSet
from agents.resilience.exercises import Exercise
from agents.resilience.explain import MIN_SEVERITY, Comparison, DependencyPath, GroupBenefit, Hit, Link, key_paths
from agents.resilience.lab import BranchRecord
from agents.resilience.network import Network
from agents.resilience.simulate import Consumption, Metrics, Outcome, TimePoint
from api.models import Arc, CascadeHit, CascadeResponse, CascadeStage, Node, PlatformExposure, QueryTrace, ReachProbe
from api.nodes import is_located, make_node, with_status
from api.resilience_models import (BranchView, CandidateView, ConsumptionView, DecisionView, DisruptionView,
                                   GroupView, LinkView, MetricsView, PathView, RecoveryView, StatePoint,
                                   TimePointView)

REACH_DEPTH = 16
STATE_STATUS = {"lost": "lost", "relocated": "lost", "residual": "at_risk", "improved": "at_risk"}


def node_of(net: Network, eid: str, status: str | None = None) -> Node:
    """API Node for an entity; a Route is drawn at the midpoint of its two terminals."""
    e = net.entity(eid)
    props = dict(e.props)
    if e.label == "Route" and eid in net.route_ends:
        a, b = (net.entity(x) for x in net.route_ends[eid])
        props["latitude"] = (a.num("latitude") + b.num("latitude")) / 2
        props["longitude"] = (a.num("longitude") + b.num("longitude")) / 2
    return with_status(make_node(e.node_id, e.label, props), status)


def metrics_view(m: Metrics) -> MetricsView:
    return MetricsView(**asdict(m))


def consumption_view(net: Network, c: Consumption) -> ConsumptionView:
    exhausted = c.stock_exhausted_h
    return ConsumptionView(
        stock_released_t=c.stock_released_t, reserves_drawn=len(c.stock_released_by_reserve),
        reserves_exhausted=len(exhausted), first_exhausted_h=min(exhausted.values()) if exhausted else None,
        generators=c.generators, generator_fuel_t=c.generator_fuel_t, aircraft_sorties=c.aircraft_sorties,
        route_tonnes={net.entity(r).name: t for r, t in c.route_tonnes.items()},
        provider_spare_t_day=c.provider_spare_t_day, programme_people=c.programme_people)


def timeline_view(points: Sequence[TimePoint]) -> list[TimePointView]:
    return [TimePointView(**asdict(p)) for p in points]


def branch_view(r: BranchRecord) -> BranchView:
    return BranchView(branch=r.branch, role=r.role, plan_id=r.plan_id, parent=r.parent,  # type: ignore[arg-type]
                      verified=r.verified)


def path_view(p: DependencyPath) -> PathView:
    return PathView(names=[s.name for s in p.steps], via=[s.via for s in p.steps], severity=p.severity)


def event_origin(net: Network, ex: Exercise, origins: Sequence[Node]) -> Node:
    """The event itself, drawn at the centroid of its located initial failures."""
    pts = [n for n in origins if is_located(n)]
    lat = sum(n.lat for n in pts) / len(pts) if pts else None  # type: ignore[misc]
    lon = sum(n.lon for n in pts) / len(pts) if pts else None  # type: ignore[misc]
    return Node(id=net.entity(ex.scenario_id).node_id, kind="other", label="Scenario", name=ex.title, lat=lat,
                lon=lon, synthetic=True, status="lost", importance=1.0)


def _stage(net: Network, layer: Sequence[Hit]) -> CascadeStage:
    hits, arcs = [], []
    for h in layer:
        node, parent = node_of(net, h.eid, "at_risk"), node_of(net, h.parent)
        hits.append(CascadeHit(node=node, degree=h.degree, severity=h.severity, parent_id=parent.id, via=h.via))
        if is_located(node) and is_located(parent):
            arcs.append(Arc(source=(parent.lon, parent.lat), target=(node.lon, node.lat),  # type: ignore[arg-type]
                            source_id=parent.id, target_id=node.id, hop=h.degree, rel=h.via))
    return CascadeStage(degree=layer[0].degree, hits=hits, arcs=arcs, count=len(hits),
                        mean_severity=round(sum(x.severity for x in hits) / len(hits), 3))


def cascade_view(net: Network, ex: Exercise, outcome: Outcome, layers: Sequence[Sequence[Hit]], branch: str,
                 reach: tuple[str, int, float | None], traces: Sequence[QueryTrace], latency_ms: float) -> CascadeResponse:
    origins = [node_of(net, e, "lost") for e in sorted(outcome.initial)]
    stages = [_stage(net, layer) for layer in layers if layer]
    platforms = []
    for mission, capability in net.capability_of.items():
        loss = round(1.0 - outcome.avail_min.get(capability, 1.0), 3)
        if loss >= MIN_SEVERITY:
            cap = net.entity(capability)
            platforms.append(PlatformExposure(name=cap.name, archetype=cap.get("archetype"), severity=loss,
                                              facility_id=net.entity(mission).node_id))
    cypher, reached, ms = reach
    return CascadeResponse(
        engine="turingdb" if ms is not None else "fixtures", latency_ms=latency_ms, roundtrip_ms=latency_ms,
        queries=list(traces), branch=branch, origin=event_origin(net, ex, origins), origin_kind="event",
        min_severity=MIN_SEVERITY, stages=stages, max_degree=len(stages), graph_hops=len(stages),
        total_affected=sum(s.count for s in stages),
        reach=ReachProbe(cypher=cypher, depth_limit=REACH_DEPTH, reached=reached, ms=ms),
        platforms=sorted(platforms, key=lambda p: (-p.severity, p.name)), connected=bool(stages),
        origins=origins, measure="service_loss")


def reach_query(scenario_id: str) -> str:
    return (f"MATCH (s:Scenario {{entity_id: '{scenario_id}'}})-[:DISABLES]->(o)<-[:DEPENDS_ON]-{{1,{REACH_DEPTH}}}(n) "
            "RETURN count(DISTINCT n) AS reached")


def offline_reach(net: Network, outcome: Outcome) -> int:
    """Unweighted DEPENDS_ON reach from the initial failures (what the live query counts)."""
    seen: set[str] = set()
    frontier = set(outcome.initial)
    for _ in range(REACH_DEPTH):
        frontier = {d.consumer for p in frontier for d in net.dependents.get(p, ())} - seen
        seen |= frontier
    return len(seen)


def disruption_view(net: Network, ex: Exercise, cands: CandidateSet, cascade: CascadeResponse,
                    record: BranchRecord) -> DisruptionView:
    d = cands.disruption
    return DisruptionView(scenario_id=ex.scenario_id, title=ex.title, hours=ex.hours,  # type: ignore[arg-type]
                          branch=branch_view(record), cascade=cascade, metrics=metrics_view(d.metrics),
                          timeline=timeline_view(d.timeline), paths=[path_view(p) for p in key_paths(net, d)],
                          unavailable=list(cands.excluded))


def _link(net: Network, link: Link) -> LinkView | None:
    a, b = node_of(net, link.source), node_of(net, link.target)
    if not (is_located(a) and is_located(b)):
        return None
    return LinkView(kind=link.kind, source=(a.lon, a.lat), target=(b.lon, b.lat),  # type: ignore[arg-type]
                    source_id=a.id, target_id=b.id, label=link.label, group=link.group)


def recovery_view(net: Network, ex: Exercise, cands: CandidateSet, decision: Decision, record: BranchRecord,
                  disruption_branch: str, comparison: Comparison, groups: Sequence[GroupBenefit],
                  limitations: Sequence[str], links: Sequence[Link]) -> RecoveryView:
    chosen = cands.get(decision.plan_id).outcome
    candidates = [CandidateView(plan_id=c.plan.plan_id, title=c.plan.title, summary=c.plan.summary,
                                actions=len(c.plan.actions), rank=i + 1, chosen=c.plan.plan_id == decision.plan_id,
                                metrics=metrics_view(c.outcome.metrics),
                                consumption=consumption_view(net, c.outcome.consumption))
                  for i, c in enumerate(cands.candidates)]
    points = [StatePoint(node=node_of(net, s.eid, STATE_STATUS.get(s.state)), state=s.state,  # type: ignore[arg-type]
                         before=round(s.before, 3), after=round(s.after, 3),
                         receiver_id=net.entity(s.receiver).node_id if s.receiver else None)
              for s in comparison.states]
    return RecoveryView(
        scenario_id=ex.scenario_id, title=ex.title, hours=ex.hours,  # type: ignore[arg-type]
        disruption_branch=disruption_branch, branch=branch_view(record),
        decision=DecisionView(mode=decision.mode, plan_id=decision.plan_id,  # type: ignore[arg-type]
                              rationale=decision.rationale, model=decision.model, calls=decision.calls,
                              reason=decision.reason),
        candidates=candidates, before=metrics_view(cands.disruption.metrics), after=metrics_view(chosen.metrics),
        before_timeline=timeline_view(cands.disruption.timeline), after_timeline=timeline_view(chosen.timeline),
        consumption=consumption_view(net, chosen.consumption), groups=[GroupView(**asdict(g)) for g in groups],
        limitations=list(limitations), counts=dict(comparison.counts),
        services_relocated=comparison.services_relocated, programmes_relocated=comparison.programmes_relocated,
        points=[p for p in points if is_located(p.node)],
        links=[v for v in (_link(net, x) for x in links) if v is not None])
