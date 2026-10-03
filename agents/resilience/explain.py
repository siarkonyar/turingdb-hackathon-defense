"""Explanations derived from measured outcomes: dependency degrees, key paths, before/after states, per-action
benefit and map overlays. Pure data; the API shapes it into responses.

Dependency degree (how many DEPENDS_ON edges from an initial failure) is deliberately separate from simulation
time (when an effect or a recovery happens): degrees come from the graph, times from simulate().
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from agents.resilience.availability import FULL
from agents.resilience.cargo import BASELINE_ROUTE, limits
from agents.resilience.exercises import Exercise
from agents.resilience.network import Network
from agents.resilience.plans import Plan, group_actions
from agents.resilience.simulate import Outcome, simulate

MIN_SEVERITY = 0.05
HIT_LABELS = ("Facility", "Port", "Route")
IMPROVED = 0.05
MAX_PATHS = 4
MAX_LIMITATIONS = 8
LONG_WINDOW_H = 100.0


ROUTE_NAMES = {  # display names for the six corridor routes (the graph names are generic)
    "route:dover_calais": "Dover–Calais sea route", "route:dover_dunkirk": "Dover–Dunkirk sea route",
    "route:western_channel": "Newhaven–Dieppe sea route", "route:tunnel": "Channel Tunnel",
    "route:london_paris_air": "London–Paris air bridge", "route:kent_beauvais_air": "Ashford–Beauvais air bridge",
}


def route_name(net: Network, route: str) -> str:
    return ROUTE_NAMES.get(route, net.entity(route).name)


@dataclass(frozen=True)
class Hit:
    eid: str
    degree: int
    severity: float  # 1 - lowest availability in the window (worst point)
    parent: str  # provider one degree nearer the initial failure
    via: str  # dependency group of that edge


def cascade(net: Network, outcome: Outcome, min_severity: float = MIN_SEVERITY) -> list[list[Hit]]:
    """Breadth-first over reversed DEPENDS_ON from the initial failures, through affected nodes only."""
    severity = {e: round(1.0 - v, 3) for e, v in outcome.avail_min.items()}
    seen = set(outcome.initial)
    frontier = sorted(outcome.initial)
    layers: list[list[Hit]] = []
    degree = 0
    while frontier:
        degree += 1
        best: dict[str, Hit] = {}
        for provider in frontier:
            for dep in net.dependents.get(provider, ()):
                c = dep.consumer
                if c in seen or severity.get(c, 0.0) < min_severity:
                    continue
                prev = best.get(c)
                if prev is None or severity.get(provider, 1.0) > severity.get(prev.parent, 1.0):
                    best[c] = Hit(c, degree, severity[c], provider, dep.group)
        seen |= set(best)
        frontier = sorted(best)
        if best:
            layers.append(sorted((h for h in best.values() if net.entity(h.eid).label in HIT_LABELS),
                                 key=lambda h: (-h.severity, h.eid)))
    while layers and not layers[-1]:
        layers.pop()
    return layers


@dataclass(frozen=True)
class PathStep:
    eid: str
    name: str
    via: str | None  # the dependency group linking it to the previous step


@dataclass(frozen=True)
class DependencyPath:
    steps: tuple[PathStep, ...]
    severity: float


def _parents(net: Network, outcome: Outcome) -> dict[str, tuple[str, str]]:
    """consumer -> (parent, via) for every affected node, platforms included (cascade() reports fewer labels)."""
    severity = {e: 1.0 - v for e, v in outcome.avail_min.items()}
    seen, frontier, out = set(outcome.initial), sorted(outcome.initial), {}
    while frontier:
        nxt = {}
        for provider in frontier:
            for dep in net.dependents.get(provider, ()):
                if dep.consumer not in seen and severity.get(dep.consumer, 0.0) >= MIN_SEVERITY:
                    nxt.setdefault(dep.consumer, (provider, dep.group))
        out.update(nxt)
        seen |= set(nxt)
        frontier = sorted(nxt)
    return out


def key_paths(net: Network, outcome: Outcome) -> list[DependencyPath]:
    """Chains from an initial failure to: the deepest programme, a hospital, a route/port and a distribution hub."""
    parent = _parents(net, outcome)
    depth: dict[str, int] = {}

    def depth_of(e: str) -> int:
        if e not in depth:
            depth[e] = 0 if e not in parent else depth_of(parent[e][0]) + 1
        return depth[e]

    def role(e: str) -> str:
        return str(net.entity(e).get("role"))

    groups = (
        [e for e in parent if role(e) in ("military_hospital", "nato_support_unit", "civil_emergency_centre")],
        [e for e in parent if role(e) == "hospital"],
        [e for e in parent if net.entity(e).label in ("Route", "Port")],
        [e for e in parent if role(e) == "distribution"],
    )
    out = []
    for group in groups:
        if not group:
            continue
        end = max(group, key=lambda e: (depth_of(e), 1.0 - outcome.avail_min.get(e, 1.0), e))
        steps, cur, via = [], end, None
        while True:
            link = parent.get(cur)
            steps.append(PathStep(cur, net.entity(cur).name, link[1] if link else None))
            if link is None:
                break
            cur = link[0]
        out.append(DependencyPath(tuple(reversed(steps)), round(1.0 - outcome.avail_min.get(end, 1.0), 3)))
    return out[:MAX_PATHS]


@dataclass(frozen=True)
class FacilityState:
    eid: str
    state: str  # lost | relocated | restored | improved | residual
    before: float  # availability at the end of the window without recovery
    after: float  # availability at the end of the window with the plan
    receiver: str | None = None  # relocated: where the service continues


@dataclass(frozen=True)
class Comparison:
    states: tuple[FacilityState, ...]
    counts: Mapping[str, int]
    services_relocated: int
    programmes_relocated: int


def compare(net: Network, before: Outcome, after: Outcome) -> Comparison:
    """End-of-window state of every facility/port that the event touched, without vs with the plan."""
    moved = {t.source: t for t in after.prepared.transfers if t.kind in ("service", "programme")}
    states = []
    for e in net.entities.values():
        if e.label not in ("Facility", "Port"):
            continue
        b, a = before.avail_end.get(e.eid, 1.0), after.avail_end.get(e.eid, 1.0)
        if e.eid in after.initial and a < FULL:
            t = moved.get(e.eid)
            state = "relocated" if t and after.avail_end.get(t.receiver, 0.0) > 0 else "lost"
            states.append(FacilityState(e.eid, state, b, a, t.receiver if t else None))
        elif b < FULL <= a:
            states.append(FacilityState(e.eid, "restored", b, a))
        elif a < FULL:
            states.append(FacilityState(e.eid, "improved" if a - b >= IMPROVED else "residual", b, a))
    counts: dict[str, int] = defaultdict(int)
    for s in states:
        counts[s.state] += 1
    relocated = [s for s in states if s.state == "relocated"]
    programmes = sum(moved[s.eid].kind == "programme" for s in relocated)
    return Comparison(tuple(sorted(states, key=lambda s: s.eid)), dict(counts), len(relocated) - programmes, programmes)


@dataclass(frozen=True)
class GroupBenefit:
    key: str
    label: str
    actions: int
    ready_h: float
    capacity: str
    essential_gain: float  # percentage points of essential fulfilment lost if this group is removed
    overall_gain: float
    cargo_gain_t: float  # on-time tonnes lost if removed


GROUP_LABELS = {
    "islanded_power": "Islanded generation", "mobile_power": "Mobile generators", "release_stock": "Reserve release",
    "relocate": "Relocate services and programmes", "second_source": "Second-source exports",
}


def _route_cap(net: Network, route: str) -> tuple[float, str]:
    return min((c, k) for k, c in limits(net, route, "uk_fr"))


def _capacity(net: Network, key: str, outcome: Outcome) -> str:
    p = outcome.prepared
    if key.startswith("reroute:"):
        route = f"route:{key.split(':', 1)[1]}"
        cap, limiter = _route_cap(net, route)
        moved = outcome.consumption.route_tonnes.get(route, 0.0)
        by = "" if limiter == route else f" (set by {net.entity(limiter).name})"
        return f"≤{cap:g} t/day{by}, {net.entity(route).num('transit_hours'):g} h transit, {moved:g} t moved"
    if key in ("islanded_power", "mobile_power"):
        suffix = ":islanded_generation" if key == "islanded_power" else ":mobile_power"
        feeds = [f for f in p.feeds if f.option_id.endswith(suffix)]
        return (f"{sum(f.generators for f in feeds)} generators, {sum(f.provided_mw for f in feeds):g} MW for "
                f"{sum(len(f.loads) for f in feeds)} loads ({sum(f.load_mw for f in feeds):g} MW)")
    if key == "release_stock":
        return (f"{len(p.releases)} reserves, {sum(r.stock_t for r in p.releases):g} t stored, "
                f"{outcome.consumption.stock_released_t:g} t released")
    transfers = [t for t in p.transfers if (t.kind == "export") == (key == "second_source")]
    people = sum(t.people for t in transfers)
    return f"{sum(t.tonnes_day for t in transfers):g} t/day spare output" + (f", {people:g} people" if people else "")


def benefits(net: Network, ex: Exercise, plan: Plan, full: Outcome) -> list[GroupBenefit]:
    """Measured benefit of each action group: re-simulate the plan without it (leave one group out)."""
    out = []
    for key, actions in group_actions(plan).items():
        rest = Plan(plan.plan_id, plan.title, plan.summary, tuple(a for a in plan.actions if a not in actions))
        without = simulate(net, ex, rest)
        m, w = full.metrics, without.metrics
        label = GROUP_LABELS.get(key) or f"Reroute via the {route_name(net, 'route:' + key.split(':', 1)[1])}"
        out.append(GroupBenefit(key, label, len(actions),
                                min(net.entity(a.option_id).num("activation_hours") for a in actions),
                                _capacity(net, key, full),
                                round(100 * (m.essential_fulfilment - w.essential_fulfilment), 1),
                                round(100 * (m.overall_fulfilment - w.overall_fulfilment), 1),
                                round(m.cargo_on_time_t - w.cargo_on_time_t, 1)))
    return sorted(out, key=lambda g: (g.ready_h, g.key))


def limitations(net: Network, outcome: Outcome, excluded: Sequence[str]) -> list[str]:
    """Residual limits, each traceable to a graph property or a measured result."""
    notes: list[str] = []
    for route in outcome.consumption.route_tonnes:
        if route == BASELINE_ROUTE:
            continue
        cap, limiter = _route_cap(net, route)
        if limiter != route and cap < net.entity(route).num("capacity_tonnes_day"):
            notes.append(f"{net.entity(route).name} carries at most {cap:g} t/day: {net.entity(limiter).name} "
                         f"handles {cap:g} t/day against a route rating of "
                         f"{net.entity(route).num('capacity_tonnes_day'):g}")
    notes += [x for x in excluded if "unavailable" in x]
    m = outcome.metrics
    if m.cargo_unmet_t > 0:
        notes.append(f"{m.cargo_unmet_t:,.0f} t of {m.cargo_scheduled_t:,.0f} t scheduled cargo is not delivered in "
                     f"the window; {m.cargo_delayed_t:,.0f} t arrives after its deadline")
    reasons: dict[str, list[str]] = defaultdict(list)
    for c, why in outcome.unmet_reasons.items():
        reasons[why].append(c.split(":")[-1])
    for why, sectors in sorted(reasons.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:2]:
        notes.append(f"{why}: {', '.join(sorted(set(sectors)))}")
    if outcome.consumption.stock_exhausted_h:
        first = min(outcome.consumption.stock_exhausted_h.values())
        notes.append(f"{len(outcome.consumption.stock_exhausted_h)} reserves run out, the first at hour {first:g}")
    if m.capabilities_below_minimum:
        notes.append(f"{m.capabilities_below_minimum} of {m.capabilities_total} service capabilities stay below "
                     "their 80% minimum on average")
    lost = [e for e in outcome.initial if net.entity(e).label == "Facility"]
    if lost and outcome.hours > LONG_WINDOW_H:
        notes.append(f"{len(lost)} destroyed facilities stay lost: continuity options relocate service, "
                     "they never rebuild an asset")
    return notes[:MAX_LIMITATIONS]


@dataclass(frozen=True)
class Link:
    kind: str  # route | power | stock | relocation | export
    source: str
    target: str
    label: str
    group: str  # the action group (plans.group_key) this link belongs to: the recovery stepper reveals by group


def links(net: Network, outcome: Outcome) -> list[Link]:
    """Recovery routes and allocation arcs for the map, each labelled with its measured quantity."""
    p, out = outcome.prepared, []
    for r in p.routes:
        a, b = net.route_ends[r.route]
        moved = outcome.consumption.route_tonnes.get(r.route, 0.0)
        cap, _ = _route_cap(net, r.route)
        out.append(Link("route", a, b, f"{route_name(net, r.route)}: ≤{cap:g} t/day, {moved:g} t moved, "
                                       f"ready +{r.ready_h:g} h", f"reroute:{r.route.split(':', 1)[1]}"))
    for f in p.feeds:
        site = net.stored_at.get(f.stock, f.stock)
        for load in f.loads:
            group = "islanded_power" if f.option_id.endswith(":islanded_generation") else "mobile_power"
            out.append(Link("power", site, load, f"{f.provided_mw:g} MW generator, ready +{f.ready_h:g} h", group))
    released = outcome.consumption.stock_released_by_reserve
    for r in p.releases:
        if released.get(r.reserve, 0.0) > 0:
            out.append(Link("stock", r.storage, r.service,
                            f"{released[r.reserve]:g} t released, ready +{r.ready_h:g} h", "release_stock"))
    for t in p.transfers:
        if t.kind == "export":
            origin = next(c.origin for c in net.consignments if c.eid == t.receiver)
            out.append(Link("export", t.provider, origin,
                            f"{t.tonnes_day:g} t/day replacement, ready +{t.ready_h:g} h", "second_source"))
        else:
            what = f"{t.people:g} people" if t.kind == "programme" else f"{t.tonnes_day:g} t/day"
            out.append(Link("relocation", t.source, t.receiver, f"{what} relocated, ready +{t.ready_h:g} h",
                            "relocate"))
    return out
