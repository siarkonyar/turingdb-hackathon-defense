"""Time-stepped measurement of one exercise under one plan (or none).

The window is cut into segments at every instant something changes (day boundaries, action readiness,
generator fuel and stock-release expiry). Per segment:
1. operability pass: availability with cargo assumed present, to know which routes, origins and receivers work;
2. per day: cargo split over routes under shared capacity (cargo.py) -> delivered fraction at import customs;
3. final pass: availability with delivered cargo, generator-fed loads and released stock. Stock is drawn down
   sequentially, never below zero, and cold-chain stock is released only from powered storage.
Demand fulfilment is time-weighted; displaced demand of a destroyed service counts only where a validated
transfer gives it a surviving receiving site. Nothing is delivered to a destroyed facility.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from agents.resilience.availability import FULL, Conditions, evaluate, group_value, grouped, has_power, operable
from agents.resilience.cargo import DayFlow, Shipment, allocate_day
from agents.resilience.exercises import HOURS_PER_DAY, Exercise, down_at, targets
from agents.resilience.network import Network
from agents.resilience.plans import NO_PLAN, Plan, Prepared, Transfer, prepare

REPORTED_LABELS = ("Facility", "Port")
CAPABILITY_MINIMUM = 0.8  # programme facilities declare minimum_service_fraction = 0.8
EPS = 1e-9


@dataclass(frozen=True)
class TimePoint:
    hour: float
    essential: float  # instantaneous priority-1 demand fulfilment
    overall: float
    capabilities_ok: int  # service capabilities at or above their minimum fraction


@dataclass(frozen=True)
class Metrics:
    essential_fulfilment: float  # time-weighted, priority-1 demand
    overall_fulfilment: float
    demands_below_minimum: int
    capabilities_below_minimum: int
    capabilities_total: int
    cargo_scheduled_t: float
    cargo_on_time_t: float
    cargo_delayed_t: float
    cargo_unmet_t: float
    affected_facilities: int  # facilities/ports below full service at any time in the window
    affected_at_end: int  # still below full service in the last segment
    essential_recovery_h: float | None  # first hour essential fulfilment reaches 80% (None: never)
    cost_units: float


@dataclass(frozen=True)
class Consumption:
    stock_released_t: float
    stock_released_by_reserve: Mapping[str, float]
    stock_exhausted_h: Mapping[str, float]  # reserve -> hour it ran out
    generators: int
    generator_fuel_t: float
    aircraft_sorties: int
    route_tonnes: Mapping[str, float]  # moved within the window, all days
    provider_spare_t_day: float
    programme_people: float


@dataclass(frozen=True)
class Outcome:
    scenario_id: str
    plan: Plan
    prepared: Prepared
    initial: frozenset[str]
    metrics: Metrics
    timeline: tuple[TimePoint, ...]
    shipments: tuple[Shipment, ...]
    consumption: Consumption
    avail_mean: Mapping[str, float]
    avail_min: Mapping[str, float]
    avail_end: Mapping[str, float]
    demand_fulfilment: Mapping[str, float]
    unmet_reasons: Mapping[str, str]  # consignment -> first limiting reason seen
    hours: float


def breakpoints(ex: Exercise, prep: Prepared) -> list[float]:
    marks = {0.0, ex.hours, *(d * HOURS_PER_DAY for d in range(ex.days))}
    for f in prep.feeds:
        marks |= {f.ready_h, f.until_h}
    for r in prep.releases:
        marks |= {r.ready_h, r.until_h}
    marks |= {r.ready_h for r in prep.routes} | {t.ready_h for t in prep.transfers}
    return sorted(m for m in marks if 0.0 <= m <= ex.hours)


class _Run:
    """One measurement: the operability pass and the daily cargo split, ready for the final pass."""

    def __init__(self, net: Network, ex: Exercise, plan: Plan) -> None:
        self.net, self.ex, self.plan = net, ex, plan
        self.initial = frozenset(targets(net, ex))
        self.prep = prepare(net, ex, plan, self.initial)
        marks = breakpoints(ex, self.prep)
        self.segments = list(zip(marks[:-1], marks[1:]))
        self.starts = [s for s, _ in self.segments]
        receivers = {c.receiver: 1.0 for c in net.consignments}
        self.pre = [evaluate(net, self.conditions(s, receivers)) for s, _ in self.segments]
        exports: dict[str, list[Transfer]] = defaultdict(list)
        for t in self.prep.transfers:
            if t.kind == "export":
                exports[t.receiver].append(t)
        self.days: list[DayFlow] = [allocate_day(net, ex, d, self.prep.routes, exports, self.pre_at)
                                    for d in range(ex.days)]

    def powered(self, t: float) -> frozenset[str]:
        return frozenset(x for f in self.prep.feeds if f.ready_h <= t < f.until_h for x in f.loads)

    def conditions(self, t: float, inflow: Mapping[str, float], extra: Mapping[str, float] | None = None) -> Conditions:
        return Conditions(down_at(self.ex, self.initial, t), self.powered(t), MappingProxyType(dict(inflow)),
                          MappingProxyType(dict(extra or {})))

    def pre_at(self, t: float) -> Mapping[str, float]:
        i = max(0, bisect.bisect_right(self.starts, min(t, self.ex.hours - EPS)) - 1)
        return self.pre[i]


class _StockLedger:
    """Reserve tonnes, drawn down sequentially; one reserve feeds exactly one service."""

    def __init__(self, run: _Run) -> None:
        self.left = {r.reserve: r.stock_t for r in run.prep.releases}
        self.released: dict[str, float] = defaultdict(float)
        self.exhausted: dict[str, float] = {}

    def release(self, run: _Run, start: float, hours: float, base: Mapping[str, float],
                cond: Conditions) -> dict[str, float]:
        """Stock fills each serviceable gap for this segment; returns service -> extra supply fraction."""
        net, extra = run.net, {}
        demand_of = {d.service: d.tonnes_day for d in net.demands}
        for r in run.prep.releases:
            if not (r.ready_h <= start < r.until_h) or self.left[r.reserve] <= EPS:
                continue
            if operable(net, r.service, base, cond) <= EPS:
                continue  # the service cannot hand anything out
            if r.cold_chain and not has_power(net, r.storage, base, cond):
                continue  # unpowered cold store: the stock is not usable
            deps = grouped(net.depends.get(r.service, ())).get("consumables", [])
            gap = 1.0 - (group_value(r.service, "consumables", deps, base, cond) if deps else 1.0)
            rate = min(gap * demand_of[r.service], r.rate_t_day, self.left[r.reserve] * HOURS_PER_DAY / hours)
            if rate <= EPS:
                continue
            used = rate * hours / HOURS_PER_DAY
            self.left[r.reserve] -= used
            self.released[r.reserve] += used
            if self.left[r.reserve] <= 1e-6:
                self.exhausted.setdefault(r.reserve, start + hours)
            extra[r.service] = rate / demand_of[r.service]
        return extra


def _fulfilment(run: _Run, avail: Mapping[str, float], start: float) -> dict[str, float]:
    """Per-demand served fraction now. Displaced demand counts only at a surviving receiving site."""
    moved: dict[str, list[Transfer]] = defaultdict(list)
    for t in run.prep.transfers:
        if t.kind == "service" and t.ready_h <= start:
            moved[t.source].append(t)
    out = {}
    for d in run.net.demands:
        if run.ex.destroys and d.service in run.initial:
            out[d.eid] = min(1.0, sum(t.tonnes_day / d.tonnes_day * avail.get(t.receiver, 0.0)
                                      for t in moved.get(d.service, ())))
        else:
            out[d.eid] = avail.get(d.service, 1.0)
    return out


def _capabilities(run: _Run, avail: Mapping[str, float], start: float) -> dict[str, float]:
    relocated = {t.source: t for t in run.prep.transfers if t.kind == "programme" and t.ready_h <= start}
    out = {}
    for mission, capability in run.net.capability_of.items():
        if run.ex.destroys and mission in run.initial:
            t = relocated.get(mission)
            out[capability] = avail.get(t.receiver, 0.0) if t else 0.0
        else:
            out[capability] = avail.get(capability, 1.0)
    return out


def _weighted(values: Mapping[str, float], weight: Mapping[str, float], priority: Mapping[str, int],
              only: int | None) -> float:
    keys = [k for k in values if only is None or priority[k] == only]
    total = sum(weight[k] for k in keys)
    return round(sum(values[k] * weight[k] for k in keys) / total, 4) if total else 1.0


@dataclass
class _Totals:
    mean: dict[str, float]
    low: dict[str, float]
    served: dict[str, float]
    caps: dict[str, float]
    timeline: list[TimePoint]
    final: Mapping[str, float]


def simulate(net: Network, ex: Exercise, plan: Plan = NO_PLAN) -> Outcome:
    """Measure the exercise under `plan`. Raises PlanRejected for anything the graph does not support."""
    run = _Run(net, ex, plan)
    ledger = _StockLedger(run)
    tot = _Totals(defaultdict(float), {}, defaultdict(float), defaultdict(float), [], {})
    priority = {d.eid: d.priority for d in net.demands}
    weight = {d.eid: d.tonnes_day for d in net.demands}
    for start, end in run.segments:
        hours, share = end - start, (end - start) / ex.hours
        inflow = run.days[int(start // HOURS_PER_DAY)].delivered
        cond = run.conditions(start, inflow)
        base = evaluate(net, cond)
        extra = ledger.release(run, start, hours, base, cond)
        tot.final = evaluate(net, run.conditions(start, inflow, extra)) if extra else base
        for eid, v in tot.final.items():
            tot.mean[eid] += v * share
            tot.low[eid] = min(tot.low.get(eid, 1.0), v)
        now = _fulfilment(run, tot.final, start)
        for eid, v in now.items():
            tot.served[eid] += v * share
        caps = _capabilities(run, tot.final, start)
        for eid, v in caps.items():
            tot.caps[eid] += v * share
        tot.timeline.append(TimePoint(start, _weighted(now, weight, priority, 1),
                                      _weighted(now, weight, priority, None),
                                      sum(v >= CAPABILITY_MINIMUM - EPS for v in caps.values())))
    return _outcome(run, tot, ledger)


def _outcome(run: _Run, tot: _Totals, ledger: _StockLedger) -> Outcome:
    net, ex, prep = run.net, run.ex, run.prep
    shipments = tuple(s for day in run.days for s in day.shipments)
    scheduled = sum(c.tonnes for c in net.consignments) * ex.days
    on_time = sum(s.tonnes for s in shipments if s.on_time)
    delayed = sum(s.tonnes for s in shipments if not s.on_time)
    reported = [e.eid for e in net.entities.values() if e.label in REPORTED_LABELS]
    minimum = {d.eid: d.minimum for d in net.demands}
    priority = {d.eid: d.priority for d in net.demands}
    weight = {d.eid: d.tonnes_day for d in net.demands}
    reasons: dict[str, str] = {}
    for day in run.days:
        for k, v in day.reasons.items():
            reasons.setdefault(k, v)
    route_t: dict[str, float] = defaultdict(float)
    for s in shipments:
        route_t[s.route] += s.tonnes
    fuel = sum(f.generators * f.fuel_t_day * max(0.0, min(f.until_h, ex.hours) - f.ready_h) / HOURS_PER_DAY
               for f in prep.feeds)
    metrics = Metrics(
        essential_fulfilment=_weighted(tot.served, weight, priority, 1),
        overall_fulfilment=_weighted(tot.served, weight, priority, None),
        demands_below_minimum=sum(tot.served[k] < minimum[k] - EPS for k in tot.served),
        capabilities_below_minimum=sum(v < CAPABILITY_MINIMUM - EPS for v in tot.caps.values()),
        capabilities_total=len(tot.caps),
        cargo_scheduled_t=round(scheduled, 1), cargo_on_time_t=round(on_time, 1), cargo_delayed_t=round(delayed, 1),
        cargo_unmet_t=round(max(0.0, scheduled - on_time - delayed), 1),
        affected_facilities=sum(tot.low.get(e, 1.0) < FULL for e in reported),
        affected_at_end=sum(tot.final.get(e, 1.0) < FULL for e in reported),
        essential_recovery_h=next((p.hour for p in tot.timeline if p.essential >= 0.8), None),
        cost_units=prep.cost_units)
    consumption = Consumption(
        stock_released_t=round(sum(ledger.released.values()), 2),
        stock_released_by_reserve=MappingProxyType(
            {k: round(v, 3) for k, v in sorted(ledger.released.items()) if v > EPS}),
        stock_exhausted_h=MappingProxyType(dict(sorted(ledger.exhausted.items()))),
        generators=sum(f.generators for f in prep.feeds), generator_fuel_t=round(fuel, 2),
        aircraft_sorties=sum(n for day in run.days for n in day.sorties.values()),
        route_tonnes=MappingProxyType({k: round(v, 1) for k, v in sorted(route_t.items())}),
        provider_spare_t_day=round(sum(t.tonnes_day for t in prep.transfers), 2),
        programme_people=sum(t.people for t in prep.transfers))
    return Outcome(ex.scenario_id, run.plan, prep, run.initial, metrics, tuple(tot.timeline), shipments, consumption,
                   MappingProxyType(dict(tot.mean)), MappingProxyType(dict(tot.low)), MappingProxyType(dict(tot.final)),
                   MappingProxyType(dict(tot.served)), MappingProxyType(reasons), ex.hours)
