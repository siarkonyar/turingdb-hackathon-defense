"""Daily cross-border cargo allocation under shared capacity.

Each day every consignment departs once (recurring_interval_hours = 24). Its cargo is split over the usable
routes, highest priority and shortest deadline first. One ledger per day holds every shared limit, so a tonne
is reserved on all of them at once and never counted twice:
- the route's `capacity_tonnes_day`, shared by both directions and every product;
- each terminal's handling (`handling_tonnes_day` for ports, `throughput_tonnes_day` for tunnel/airport
  facilities), shared by every route using that terminal;
- each last-mile road hub's `throughput_tonnes_day`, shared likewise;
- for air, the departing side's aircraft pool: units x payload x rotations per day.
A route is usable only while its own dependencies (terminals, power, communications, fuel, last mile,
aircraft, sea access) are available. Arrival = departure + handling + transit; domestic road legs are not
timed because the graph has no calibrated road travel times.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from agents.resilience.exercises import HOURS_PER_DAY, Exercise
from agents.resilience.network import Consignment, Network
from agents.resilience.plans import SHORT_DEADLINE_H, RouteOpen, Transfer

BASELINE_ROUTE = "route:dover_calais"
DEPARTING_COUNTRY = {"uk_fr": "GBR", "fr_uk": "FRA"}
EPS = 1e-6


@dataclass(frozen=True)
class Shipment:
    day: int
    consignment: str
    route: str
    tonnes: float
    depart_h: float
    arrive_h: float
    on_time: bool
    replacement: bool  # carried for a second-source provider rather than the original exporter


@dataclass(frozen=True)
class DayFlow:
    day: int
    delivered: Mapping[str, float]  # import customs facility -> on-time fraction of its consignment
    shipments: tuple[Shipment, ...]
    unmet_t: Mapping[str, float]  # consignment -> tonnes not delivered within the window
    reasons: Mapping[str, str]  # consignment -> why cargo could not move (first limiting reason)
    sorties: Mapping[str, int]  # aircraft pool -> rotations flown: consolidated loads, ceil(tonnes / payload)


@dataclass(frozen=True)
class Lot:
    tonnes: float
    earliest_h: float
    replacement: bool


def limits(net: Network, route: str, direction: str) -> list[tuple[str, float]]:
    """Every shared capacity a tonne on this route draws on, as (ledger key, tonnes/day)."""
    r = net.entity(route)
    out = [(route, r.num("capacity_tonnes_day"))]
    for dep in net.depends.get(route, ()):
        p = net.entity(dep.provider)
        if dep.group.startswith("terminal_"):
            out.append((p.eid, p.num("handling_tonnes_day", p.num("throughput_tonnes_day"))))
        elif dep.group.startswith("last_mile_"):
            out.append((p.eid, p.num("throughput_tonnes_day")))
        elif dep.group.startswith("aircraft_") and p.get("country_code") == DEPARTING_COUNTRY[direction]:
            out.append((p.eid, p.num("available_units") * p.num("payload_tonnes") * p.num("rotations_day")))
    return out


def _usable(c: Consignment, route: str, scope: str, net: Network) -> bool:
    if scope == "short_deadline" and c.deadline_hours > SHORT_DEADLINE_H:
        return False
    return not c.cold_chain or bool(net.entity(route).get("cold_chain_capable", False))


def _lots(c: Consignment, day: int, avail: Mapping[str, float], exports: Sequence[Transfer]) -> list[Lot]:
    t0 = day * HOURS_PER_DAY
    lots = [Lot(c.tonnes * avail.get(c.origin, 1.0), t0, False)]
    for x in exports:
        hub = avail.get(x.road_hub, 1.0) if x.road_hub else 1.0
        lots.append(Lot(x.tonnes_day * min(avail.get(x.provider, 1.0), hub), max(t0, x.ready_h), True))
    return [lot for lot in lots if lot.tonnes > EPS]


def _options(net: Network, ex: Exercise, c: Consignment, lot: Lot, routes: Sequence[RouteOpen],
             t0: float, avail_at: Callable[[float], Mapping[str, float]]) -> list[tuple[bool, float, float, str]]:
    """(late, arrival, departure, route) for every route this lot could use inside the window."""
    out = []
    for opt in routes:
        depart = max(lot.earliest_h, opt.ready_h)
        if depart >= ex.hours or not _usable(c, opt.route, opt.scope, net):
            continue
        if avail_at(depart).get(opt.route, 1.0) <= EPS:
            continue
        arrive = depart + c.handling_hours + net.entity(opt.route).num("transit_hours")
        if arrive <= ex.hours:
            out.append((arrive > t0 + c.deadline_hours, arrive, depart, opt.route))
    return sorted(out)


def allocate_day(net: Network, ex: Exercise, day: int, routes: Sequence[RouteOpen],
                 exports: Mapping[str, Sequence[Transfer]], avail_at: Callable[[float], Mapping[str, float]]) -> DayFlow:
    """Split this day's departures over usable routes. `avail_at(t)` is operability with cargo assumed present."""
    t0 = day * HOURS_PER_DAY
    ledger: dict[str, float] = {}
    options = [RouteOpen("baseline", BASELINE_ROUTE, 0.0, "all"), *routes]
    shipments: list[Shipment] = []
    delivered: dict[str, float] = {}
    unmet: dict[str, float] = {}
    reasons: dict[str, str] = {}
    now = avail_at(t0)
    for c in sorted(net.consignments, key=lambda c: (c.priority, c.deadline_hours, not c.cold_chain, c.eid)):
        receiver_ok = now.get(c.receiver, 1.0)
        if receiver_ok <= EPS:
            reasons[c.eid] = f"{net.entity(c.receiver).name} cannot operate"
        budget, moved, on_time = c.tonnes * receiver_ok, 0.0, 0.0
        for lot in _lots(c, day, now, exports.get(c.eid, ())):
            left = min(lot.tonnes, budget - moved)
            plan = _options(net, ex, c, lot, options, t0, avail_at)
            for late, arrive, depart, route in plan:
                if left <= EPS:
                    break
                caps = limits(net, route, c.direction)
                take = min(left, min(ledger.setdefault(k, cap) for k, cap in caps))
                if take <= EPS:
                    continue
                for k, _ in caps:
                    ledger[k] -= take
                shipments.append(Shipment(day, c.eid, route, round(take, 4), depart, arrive, not late,
                                          lot.replacement))
                left -= take
                moved += take
                on_time += 0.0 if late else take
            if left > EPS and c.eid not in reasons:
                reasons[c.eid] = "no usable route capacity left" if plan else "no usable route in the window"
        if c.eid not in reasons and c.tonnes - moved > EPS:
            reasons[c.eid] = f"{net.entity(c.origin).name} cannot export"
        delivered[c.receiver] = min(1.0, on_time / c.tonnes) if c.tonnes else 0.0
        unmet[c.eid] = max(0.0, c.tonnes - moved)
    return DayFlow(day, MappingProxyType(delivered), tuple(shipments), MappingProxyType(unmet),
                   MappingProxyType(reasons), MappingProxyType(_sorties(net, ledger)))


def _sorties(net: Network, ledger: Mapping[str, float]) -> dict[str, int]:
    """Aircraft rotations per pool: cargo from different consignments is consolidated on the same aircraft."""
    out = {}
    for key, left in ledger.items():
        if key.startswith("aircraft:"):
            pool = net.entity(key)
            used = pool.num("available_units") * pool.num("payload_tonnes") * pool.num("rotations_day") - left
            out[key] = ceil(used / pool.num("payload_tonnes") - EPS) if used > EPS else 0
    return out
