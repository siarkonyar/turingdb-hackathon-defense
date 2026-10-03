"""Typed recovery actions, plans, and their static validation + resource allocation.

Every action names a real `RecoveryOption` attached to its target by `HAS_RECOVERY`. `prepare()` rejects
anything the graph does not support, then allocates the finite pools exactly once:
- generators per emergency reserve (`mobile_generators`), with load MW checked against `provided_mw`;
- provider spare output (`spare_tonnes_day` / `provider_spare_tonnes_day`) shared by every action using it;
- receiving programme capacity (`spare_service_people`), consumed per relocated programme.
Route, terminal, hub and aircraft capacity is time-dependent and is allocated per day in cargo.py.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from agents.resilience.exercises import Exercise
from agents.resilience.network import Entity, Network

ActionKind = Literal["reroute", "islanded_power", "mobile_power", "release_stock", "relocate", "second_source"]
Scope = Literal["all", "short_deadline"]
OPTION_KINDS: dict[str, tuple[str, ...]] = {
    "islanded_power": ("islanded_generation",),
    "mobile_power": ("mobile_power",),
    "release_stock": ("release_stock",),
    "relocate": ("relocate_service", "second_source"),
    "second_source": ("second_source",),
}
SHORT_DEADLINE_H = 24.0  # scope "short_deadline": cargo due within a day (medical, water, power, comms, cold)
PROGRAMME_ROLES = ("military_hospital", "nato_support_unit", "civil_emergency_centre")


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target: str  # the asset that carries the RecoveryOption
    option_id: str
    loads: tuple[str, ...] = ()  # islanded_power: facilities fed by the islanded generator
    scope: Scope = "all"  # reroute: which consignments may use the route


@dataclass(frozen=True)
class Plan:
    plan_id: str
    title: str
    summary: str
    actions: tuple[Action, ...]


NO_PLAN = Plan("disruption", "No recovery", "The event alone, with no recovery actions", ())


@dataclass(frozen=True)
class PowerFeed:
    option_id: str
    stock: str
    generators: int
    provided_mw: float
    load_mw: float
    loads: tuple[str, ...]
    ready_h: float
    until_h: float
    fuel_t_day: float  # per generator


@dataclass(frozen=True)
class RouteOpen:
    option_id: str
    route: str
    ready_h: float
    scope: Scope


@dataclass(frozen=True)
class Release:
    option_id: str
    service: str
    reserve: str
    storage: str
    rate_t_day: float
    stock_t: float
    ready_h: float
    until_h: float
    cold_chain: bool


@dataclass(frozen=True)
class Transfer:
    """Continuity elsewhere: displaced demand/programme at a receiving site, or replacement export output."""
    option_id: str
    kind: Literal["service", "programme", "export"]
    source: str  # the destroyed asset
    provider: str  # whose spare capacity is consumed
    receiver: str  # receiving service/programme, or the consignment for an export
    tonnes_day: float
    people: float
    ready_h: float
    road_hub: str | None


@dataclass(frozen=True)
class Prepared:
    feeds: tuple[PowerFeed, ...]
    routes: tuple[RouteOpen, ...]
    releases: tuple[Release, ...]
    transfers: tuple[Transfer, ...]
    cost_units: float


class PlanRejected(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


def _option(net: Network, a: Action, errors: list[str]) -> Entity | None:
    opt = net.entities.get(a.option_id)
    if opt is None or opt.label != "RecoveryOption":
        errors.append(f"{a.option_id} is not a recovery option in the graph")
        return None
    if a.option_id not in net.recovery.get(a.target, ()):
        errors.append(f"{a.option_id} is not attached to {a.target}")
        return None
    kind = str(opt.get("recovery_kind"))
    allowed = OPTION_KINDS.get(a.kind, (kind,) if a.kind == "reroute" and kind.startswith("reroute_") else ())
    if kind not in allowed:
        errors.append(f"{a.option_id} is a {kind} option, not usable for {a.kind}")
        return None
    return opt


def _receiving_service(net: Network, provider: str, sector: str) -> str | None:
    """Displaced demand of a destroyed service continues at the same-sector service in the provider's town."""
    candidate = f"local:{net.town_of(provider)}:{sector}:service"
    return candidate if candidate in net.entities else None


class _Allocator:
    """Static pools, each drawn down once across the whole plan."""

    def __init__(self, net: Network) -> None:
        self.net = net
        self.generators: dict[str, int] = {}
        self.spare_t: dict[str, float] = {}
        self.spare_people: dict[str, float] = {}

    def take_generators(self, stock: str, n: int) -> bool:
        left = self.generators.setdefault(stock, int(self.net.entity(stock).num("mobile_generators")))
        if n > left:
            return False
        self.generators[stock] = left - n
        return True

    def take_tonnes(self, provider: str, opt: Entity, want: float) -> float:
        e = self.net.entity(provider)
        left = self.spare_t.setdefault(provider, e.num("spare_tonnes_day", opt.num("provider_spare_tonnes_day")))
        got = max(0.0, min(want, left, opt.num("capacity_tonnes_day")))
        self.spare_t[provider] = left - got
        return got

    def take_people(self, provider: str, want: float) -> float:
        left = self.spare_people.setdefault(provider, self.net.entity(provider).num("spare_service_people"))
        got = max(0.0, min(want, left))
        self.spare_people[provider] = left - got
        return got


def prepare(net: Network, ex: Exercise, plan: Plan, initial: frozenset[str]) -> Prepared:
    """Validate the plan against the graph and the event; allocate static pools. Raises PlanRejected."""
    errors: list[str] = []
    lost = initial if ex.destroys else frozenset()
    pool = _Allocator(net)
    feeds, routes, releases, transfers = [], [], [], []
    fed: set[str] = set()
    seen: set[str] = set()
    cost = 0.0
    for a in plan.actions:
        if a.option_id in seen:
            errors.append(f"{a.option_id} is used twice")
            continue
        seen.add(a.option_id)
        opt = _option(net, a, errors)
        if opt is None:
            continue
        if a.target in lost and a.kind not in ("relocate", "second_source"):
            errors.append(f"{opt.eid}: {a.target} is destroyed; {opt.get('recovery_kind')} cannot restore it")
            continue
        gone = [p for p in net.requires.get(opt.eid, ()) if p in initial]
        if gone:
            errors.append(f"{a.option_id} needs {', '.join(gone)}, which the event has disabled")
            continue
        cost += opt.num("cost_units")
        ready, until = opt.num("activation_hours"), opt.num("activation_hours") + opt.num("duration_hours")
        if a.kind in ("islanded_power", "mobile_power"):
            feed = _power(net, a, opt, ready, until, pool, fed, errors)
            if feed:
                feeds.append(feed)
        elif a.kind == "reroute":
            routes.append(RouteOpen(opt.eid, net.requires[opt.eid][0], ready, a.scope))
        elif a.kind == "release_stock":
            release = _release(net, a, opt, ready, until, lost, errors)
            if release:
                releases.append(release)
        else:
            transfer = _transfer(net, a, opt, ready, lost, pool, errors)
            if transfer:
                transfers.append(transfer)
    if errors:
        raise PlanRejected(errors)
    return Prepared(tuple(feeds), tuple(routes), tuple(releases), tuple(transfers), round(cost, 2))


def _power(net: Network, a: Action, opt: Entity, ready: float, until: float, pool: _Allocator,
           fed: set[str], errors: list[str]) -> PowerFeed | None:
    loads = a.loads if a.kind == "islanded_power" else (a.target,)
    town = net.town_of(a.target)
    for load in loads:
        if load in fed:
            errors.append(f"{opt.eid}: {load} is fed by two generators")
            return None
        if net.town_of(load) != town or not any(d.group == "electricity" for d in net.depends.get(load, ())):
            errors.append(f"{opt.eid}: {load} is not an electrical load in {town}")
            return None
    stock = next(p for p in net.requires[opt.eid] if net.entity(p).label == "Stockpile")
    generators = int(opt.num("consumes_generators", 1))
    provided = opt.num("provided_mw") * generators
    load_mw = sum(net.entity(x).num("power_demand_mw") for x in loads)
    if load_mw > provided + 1e-9:
        errors.append(f"{opt.eid}: {load_mw:.1f} MW of load exceeds {provided:.1f} MW")
        return None
    if not pool.take_generators(stock, generators):
        errors.append(f"{opt.eid}: {stock} has no mobile generator left")
        return None
    fed.update(loads)
    fuel_hours = net.entity(stock).num("generator_fuel_hours", until - ready)
    return PowerFeed(opt.eid, stock, generators, provided, round(load_mw, 3), tuple(loads), ready,
                     min(until, ready + fuel_hours), opt.num("consumes_fuel_tonnes_day"))


def _release(net: Network, a: Action, opt: Entity, ready: float, until: float, lost: frozenset[str],
             errors: list[str]) -> Release | None:
    reserve = net.requires[opt.eid][0]
    storage = net.stored_at.get(reserve, "")
    if storage in lost:
        errors.append(f"{opt.eid}: {reserve} is stored at {storage}, which is destroyed")
        return None
    product = net.entities.get(str(net.entity(reserve).get("product_id")))
    return Release(opt.eid, a.target, reserve, storage, opt.num("consumes_tonnes_day"),
                   net.entity(reserve).num("stock_tonnes"), ready, until,
                   bool(product and product.get("cold_chain_required", False)))


def _transfer(net: Network, a: Action, opt: Entity, ready: float, lost: frozenset[str], pool: _Allocator,
              errors: list[str]) -> Transfer | None:
    if a.target not in lost:
        errors.append(f"{opt.eid}: {a.target} is not destroyed in this exercise; {a.kind} applies to destroyed assets only")
        return None
    providers = net.requires[opt.eid]
    provider = next(p for p in providers if ":road_hub" not in p)
    hub = next((p for p in providers if ":road_hub" in p), None)
    if a.kind == "second_source":
        sent = [c for c in net.consignments if c.origin == a.target]
        if not sent:
            errors.append(f"{opt.eid}: {a.target} exports nothing; second-sourcing it moves no cargo")
            return None
        got = pool.take_tonnes(provider, opt, sent[0].tonnes)
        return Transfer(opt.eid, "export", a.target, provider, sent[0].eid, got, 0.0, ready, hub)
    if str(net.entity(a.target).get("role")) in PROGRAMME_ROLES:
        people = pool.take_people(provider, opt.num("displaced_people_capacity"))
        if people <= 0:
            errors.append(f"{opt.eid}: receiving site {provider} has no spare programme capacity left")
            return None
        return Transfer(opt.eid, "programme", a.target, provider, provider, 0.0, people, ready, hub)
    demand = next((d for d in net.demands if d.service == a.target), None)
    if demand is None:
        errors.append(f"{opt.eid}: {a.target} serves no demand to relocate")
        return None
    receiver = provider if provider.endswith(":service") else _receiving_service(net, provider, demand.sector)
    if receiver is None or receiver in lost:
        errors.append(f"{opt.eid}: no surviving receiving site for {a.target}")
        return None
    got = pool.take_tonnes(provider, opt, demand.tonnes_day)
    return Transfer(opt.eid, "service", a.target, provider, receiver, got, 0.0, ready, hub)


def group_key(a: Action) -> str:
    return a.kind if a.kind != "reroute" else f"reroute:{a.option_id.rsplit(':reroute_', 1)[-1]}"


def group_actions(plan: Plan) -> dict[str, list[Action]]:
    """Plan actions grouped for reporting and leave-one-group-out benefit measurement."""
    out: dict[str, list[Action]] = defaultdict(list)
    for a in plan.actions:
        out[group_key(a)].append(a)
    return dict(out)
