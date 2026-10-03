"""Prepared, validated recovery candidates for each supported exercise.

Candidates are built only from RecoveryOptions the graph attaches to affected assets. Each one is measured by
simulate() before anyone sees it; an action the validator rejects is dropped with its reason, and every
alternative route is checked against its own dependencies under the event (power, communications, fuel,
terminals, last mile, aircraft, sea access) so an unavailable alternative is reported, never planned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agents.resilience.availability import FULL, Conditions, evaluate
from agents.resilience.exercises import Exercise, targets
from agents.resilience.network import Network
from agents.resilience.plans import PROGRAMME_ROLES, Action, Plan, PlanRejected, Scope, prepare
from agents.resilience.simulate import Outcome, simulate

PRIORITY_SECTORS = ("medical", "cold", "water")
ALL_SECTORS = ("medical", "food", "water", "fuel", "repair", "power", "comms", "shelter", "cold", "sanitation")
ALTERNATIVE_ROUTES = ("tunnel", "western_channel", "london_paris_air", "kent_beauvais_air")
MAX_REPAIR_ROUNDS = 8


@dataclass(frozen=True)
class RouteCheck:
    route: str
    option_id: str
    available: bool
    blockers: tuple[str, ...]  # names of the route's own dependencies that the event takes down


@dataclass(frozen=True)
class Candidate:
    plan: Plan
    outcome: Outcome


@dataclass(frozen=True)
class CandidateSet:
    disruption: Outcome
    candidates: tuple[Candidate, ...]  # ranked best first
    excluded: tuple[str, ...]  # actions the validator rejected while preparing, with reasons
    routes: tuple[RouteCheck, ...]

    def get(self, plan_id: str) -> Candidate:
        for c in self.candidates:
            if c.plan.plan_id == plan_id:
                return c
        raise KeyError(f"unknown candidate {plan_id!r}; prepared: {[c.plan.plan_id for c in self.candidates]}")


def score(o: Outcome) -> tuple:
    """Deterministic ranking: essential service, then all service, then cargo, then cost."""
    m = o.metrics
    return (-m.essential_fulfilment, -m.overall_fulfilment, m.cargo_unmet_t + m.cargo_delayed_t, m.cost_units)


def _act(net: Network, kind: str, target: str, option_kind: str, **kw) -> Action | None:
    opt = net.option(target, option_kind)
    return Action(kind, target, opt.eid, **kw) if opt else None  # type: ignore[arg-type]


def _reroutes(net: Network, target: str, routes: tuple[str, ...], scope: Scope = "all") -> list[Action]:
    return [a for r in routes if (a := _act(net, "reroute", target, f"reroute_{r}", scope=scope))]


def _towns(net: Network, region: str | None = None) -> list[str]:
    return sorted({str(net.town_of(e.eid)) for e in net.entities.values()
                   if e.label == "PowerPlant" and (region is None or e.get("region") == region)})


def _releases(net: Network, towns: list[str], sectors: tuple[str, ...] = PRIORITY_SECTORS) -> list[Action]:
    return [a for t in towns for s in sectors
            if (a := _act(net, "release_stock", f"local:{t}:{s}:service", "release_stock"))]


def route_checks(net: Network, ex: Exercise, target: str) -> tuple[RouteCheck, ...]:
    """Each alternative route under the event alone, judged by its own dependencies."""
    down = frozenset(targets(net, ex))
    avail = evaluate(net, Conditions(down, inflow={c.receiver: 1.0 for c in net.consignments}))
    out = []
    for r in ALTERNATIVE_ROUTES:
        opt = net.option(target, f"reroute_{r}")
        if opt is None:
            continue
        route = net.requires[opt.eid][0]
        blockers = tuple(sorted({net.entity(d.provider).name for d in net.depends.get(route, ())
                                 if avail.get(d.provider, 1.0) < FULL}))
        out.append(RouteCheck(route, opt.eid, avail.get(route, 1.0) >= FULL, blockers))
    return tuple(out)


def _usable(checks: tuple[RouteCheck, ...], wanted: tuple[str, ...]) -> tuple[str, ...]:
    ok = {c.route for c in checks if c.available}
    return tuple(r for r in wanted if f"route:{r}" in ok)


def strait_plans(net: Network, ex: Exercise, checks: tuple[RouteCheck, ...]) -> list[Plan]:
    surface = _reroutes(net, "chokepoint:dover", _usable(checks, ("tunnel", "western_channel")))
    air = _reroutes(net, "chokepoint:dover", _usable(checks, ("london_paris_air", "kent_beauvais_air")),
                    "short_deadline")
    reserves = _releases(net, _towns(net), ALL_SECTORS)
    return [
        Plan("strait-surface", "Surface reroute",
             "Split every consignment over the tunnel and the Newhaven–Dieppe crossing", tuple(surface)),
        Plan("strait-surface-air", "Surface reroute + air bridge",
             "Surface reroute, plus both air routes for cargo due within 24 hours", tuple(surface + air)),
        Plan("strait-surface-air-reserves", "Surface + air + emergency reserves",
             "Surface and air reroute, plus every town's product reserves released where imports fall short",
             tuple(surface + air + reserves)),
    ]


def _kent_feeds(net: Network, town: str, with_mobile: bool) -> list[Action]:
    """Islanded generator (one 2 MW set) plus, optionally, the reserve's two other sets as mobile power."""
    infra = [f"infra:{town}:{r}" for r in ("telecom_exchange", "water_works", "fuel_depot")]
    medical = [f"local:{town}:medical:distribution", f"local:{town}:medical:service"]
    if with_mobile:
        loads, mobile = infra + medical + [f"local:{town}:cold:distribution"], [
            f"local:{town}:cold:service", f"local:{town}:water:service"]
    else:
        loads, mobile = infra + medical + [f"local:{town}:water:service"], []
    out = [a for a in [_act(net, "islanded_power", f"grid:{town}", "islanded_generation", loads=tuple(loads))] if a]
    return out + [a for f in mobile if (a := _act(net, "mobile_power", f, "mobile_power"))]


def kent_plans(net: Network, ex: Exercise, checks: tuple[RouteCheck, ...]) -> list[Plan]:
    kent = _towns(net, region="Kent")
    islanded = [a for t in kent for a in _kent_feeds(net, t, with_mobile=False)]
    powered = [a for t in kent for a in _kent_feeds(net, t, with_mobile=True)]
    reserves = _releases(net, _towns(net))
    reroute = _reroutes(net, "route:dover_calais", _usable(checks, ("western_channel", "london_paris_air")))
    return [
        Plan("kent-islanded", "Islanded critical utilities",
             "One islanded generator per Kent town for communications, water, fuel and the medical chain",
             tuple(islanded)),
        Plan("kent-power-reserves", "Islanded + mobile power + priority-1 reserves",
             "All three generators per Kent town on the medical, cold-chain and water services, with their reserves",
             tuple(powered + reserves)),
        Plan("kent-power-reserves-reroute", "Power + reserves + independent crossings",
             "As above, plus London exports rerouted over crossings that keep their own power and last mile",
             tuple(powered + reserves + reroute)),
    ]


def _destroyed_services(net: Network, initial: frozenset[str], sectors: tuple[str, ...] | None) -> list[Action]:
    out = []
    for d in net.demands:
        if d.service in initial and (sectors is None or d.sector in sectors):
            kind = "relocate_service" if net.option(d.service, "relocate_service") else "second_source"
            if (a := _act(net, "relocate", d.service, kind)):
                out.append(a)
    return out


def _programmes(net: Network, initial: frozenset[str], roles: tuple[str, ...]) -> list[Action]:
    return [a for eid in sorted(initial) if net.entity(eid).get("role") in roles
            and (a := _act(net, "relocate", eid, "relocate_service"))]


def london_plans(net: Network, ex: Exercise, checks: tuple[RouteCheck, ...]) -> list[Plan]:
    initial = frozenset(targets(net, ex))
    essential = _destroyed_services(net, initial, PRIORITY_SECTORS) + _programmes(net, initial, ("military_hospital",))
    everything = _destroyed_services(net, initial, None) + _programmes(net, initial, PROGRAMME_ROLES)
    exports = [a for c in net.consignments if c.origin in initial
               and (a := _act(net, "second_source", c.origin, "second_source"))]
    return [
        Plan("london-essential", "Relocate essential services",
             "Move medical, cold-chain and water demand and the military hospitals to surviving sites",
             tuple(essential)),
        Plan("london-all-services", "Relocate all services and programmes",
             "Move every destroyed local service and all six programmes to surviving receiving sites",
             tuple(everything)),
        Plan("london-relocate-second-source", "Relocate + second-source exports",
             "Relocate everything, and replace London's four destroyed export inputs from other UK regions",
             tuple(everything + exports)),
    ]


Builder = Callable[[Network, Exercise, tuple[RouteCheck, ...]], list[Plan]]
BUILDERS: dict[str, tuple[str, Builder]] = {
    "scenario:strait_closure": ("chokepoint:dover", strait_plans),
    "scenario:kent_power": ("route:dover_calais", kent_plans),
    "scenario:london_loss": ("route:dover_calais", london_plans),
}


def _repair(net: Network, ex: Exercise, plan: Plan, excluded: list[str]) -> Plan:
    """Drop actions the validator rejects (e.g. a receiving site already full), recording why."""
    initial = frozenset(targets(net, ex))
    for _ in range(MAX_REPAIR_ROUNDS):
        try:
            prepare(net, ex, plan, initial)
            return plan
        except PlanRejected as exc:
            bad = {a.option_id for a in plan.actions if any(r.startswith(f"{a.option_id}:") for r in exc.reasons)}
            if not bad:
                raise
            excluded.extend(f"{plan.title}: {r}" for r in exc.reasons)
            plan = Plan(plan.plan_id, plan.title, plan.summary, tuple(a for a in plan.actions if a.option_id not in bad))
    prepare(net, ex, plan, initial)
    return plan


def prepare_candidates(net: Network, ex: Exercise) -> CandidateSet:
    target, build = BUILDERS[ex.scenario_id]
    checks = route_checks(net, ex, target)
    excluded = [f"{c.route} unavailable: needs {', '.join(c.blockers)}" for c in checks if not c.available]
    plans = [_repair(net, ex, p, excluded) for p in build(net, ex, checks)]
    measured = [Candidate(p, simulate(net, ex, p)) for p in plans if p.actions]
    ranked = tuple(sorted(measured, key=lambda c: score(c.outcome)))
    return CandidateSet(simulate(net, ex), ranked, tuple(dict.fromkeys(excluded)), checks)
