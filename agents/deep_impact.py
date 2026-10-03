"""Defence production capability on the deep supply network (supply_chain_deep inside theatre).

Read from TuringDB with a handful of linear queries, evaluated in Python (milliseconds), so the wargame can
preview candidate moves without building a branch for each.

    facility ok (0..1)  0 if gone, out of action (ops_closed), or it had a power feed on main and has none
                        now; otherwise its best export port's route factor: OVERLAND_FLOOR for a closed or
                        removed port (road / rail / air at reduced capacity), else 1 - REROUTE_LOSS x share of
                        that port's shipments that transit a blocked chokepoint; a port the facility did not use
                        on main (a reroute) runs at ALT_PORT_EFFICIENCY (longer haul, congestion)
    item production     PRODUCED_AT share-weighted mean of its facilities' ok (1 if it has no facility); an
                        export control (country, item) zeroes that country's makers of the item and, for
                        minerals/materials, that country's PRODUCTION_SHARE
    item availability   min of production and each CONTAINS child's buffered availability:
                        1 - (1 - child availability) x (1 - TIER_BUFFER) (safety stock and substitution absorb
                        part of an input shortfall at every tier); a stockpiled item never drops below
                        STOCKPILE_FLOOR
    capability loss     1 - sum(platform availability x weight) / sum(weight); a platform's weight is half an
                        equal programme share, half its share of annual value (demand x unit cost): raw value
                        alone puts 91% of capability in 5 of 40 platforms
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace

REROUTE_LOSS = 0.35  # a blocked chokepoint sends shipments the long way (Cape, Arctic): 35% of that flow lost
OVERLAND_FLOOR = 0.4  # a closed export port: road / rail / air keep 40% of a facility's outbound flow
ALT_PORT_EFFICIENCY = 0.8  # exporters moved to another port keep 80% (longer haul, congestion)
STOCKPILE_FLOOR = 0.8
EQUAL_SHARE = 0.5  # platform weight = EQUAL_SHARE / N + (1 - EQUAL_SHARE) x value share
TIER_BUFFER = 0.3  # share of an input shortfall absorbed at each bill-of-materials tier
CONTROLS_PROP, CLOSED_PROP = "ops_controls", "ops_closed"
ITEM_LABELS = ("Platform", "System", "Subsystem", "Assembly", "Subassembly", "Component", "Material", "Mineral")


@dataclass(frozen=True)
class Static:
    """Main-branch structure that the wargame never edits (bill of materials, routing, reference data)."""
    platforms: dict[str, tuple[str, str, float]]  # node -> (item_id, name, weight)
    children: dict[str, tuple[str, ...]]  # item -> CONTAINS children
    items: dict[str, tuple[str, str, str]]  # node -> (item_id, name, label)
    country_share: dict[str, dict[str, float]]  # mineral/material -> {country_code: share_pct}
    port_choke: dict[str, dict[str, float]]  # port -> {chokepoint: share of its sea shipments}
    facilities: dict[str, dict]  # node -> {facility_id, name, type, cc, lat, lon, utilization}
    ports: dict[str, dict]  # node -> {port_id, name, cc, lat, lon}
    chokes: dict[str, dict]  # node -> {waypoint_id, name, lat, lon}
    countries: dict[str, str]  # country_code -> node
    powered_main: frozenset[str]  # facilities with a POWERED_BY feed on main
    ships_main: dict[str, frozenset[str]]  # facility -> its SHIPS_VIA ports on main
    allied: frozenset[str]  # NATO or EU country codes
    item_weight: dict[str, float] = field(default_factory=dict)  # platform value that depends on the item
    order: tuple[str, ...] = ()  # items, children before parents
    original_makers: dict[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class State:
    """What a branch changed: the mutable part of the deep layer."""
    facilities: frozenset[str]
    ports: frozenset[str]
    produced_at: dict[str, tuple[tuple[str, float], ...]]  # item -> ((facility, share_pct), ...)
    ships_via: dict[str, tuple[str, ...]]  # facility -> ports
    powered: frozenset[str]
    closed: frozenset[str] = frozenset()  # facilities / ports out of action
    blocked: frozenset[str] = frozenset()  # chokepoints
    controls: frozenset[str] = frozenset()  # export controls, "CC|item-node"
    stockpiled: frozenset[str] = frozenset()  # items
    protected: frozenset[str] = frozenset()  # facilities / ports
    capacity_limited: bool = False  # strategic matches only; old recordings retain their original rules
    port_capacity_factor: float = 1.0


@dataclass
class Result:
    loss: float
    platform_avail: dict[str, float]
    facility_ok: dict[str, float]
    item_avail: dict[str, float]


# ---------------------------------------------------------------------- evaluation (pure)


def port_factor(static: Static, state: State, port: str) -> float:
    if port not in state.ports or port in state.closed:
        if state.capacity_limited and port in state.ports and port in state.protected:
            return 0.7
        return OVERLAND_FLOOR
    blocked = sum(share for c, share in static.port_choke.get(port, {}).items() if c in state.blocked)
    return max(0.0, 1.0 - REROUTE_LOSS * min(1.0, blocked))


def facility_ok(static: Static, state: State, fac: str) -> float:
    if fac not in state.facilities:
        return 0.0
    output = 1.0
    if fac in state.closed:
        if state.capacity_limited and fac in state.protected:
            output = 0.5
        else:
            return 0.0
    if fac in static.powered_main and fac not in state.powered:
        return 0.0
    ports = state.ships_via.get(fac, ())
    home = static.ships_main.get(fac, frozenset())
    if not ports:
        return output * (OVERLAND_FLOOR if home else 1.0)
    return output * max(port_factor(static, state, p) * (1.0 if p in home or not home else ALT_PORT_EFFICIENCY)
               for p in ports)


def evaluate(static: Static, state: State) -> Result:
    ok = {f: facility_ok(static, state, f) for f in static.facilities}
    if state.capacity_limited:
        # Exporters choose one route. Extra traffic shares finite spare capacity with existing traffic.
        homes: dict[str, int] = defaultdict(int)
        users: dict[str, list[str]] = defaultdict(list)
        for ps in static.ships_main.values():
            for p in ps:
                homes[p] += 1
        for f, ps in state.ships_via.items():
            live = [p for p in ps if p in state.ports and (p not in state.closed or p in state.protected)]
            if live and ok.get(f, 0) > 0:
                p = max(sorted(live), key=lambda p: port_factor(static, state, p) *
                        (1 if p in static.ships_main.get(f, ()) else ALT_PORT_EFFICIENCY))
                users[p].append(f)
        for p, fs in users.items():
            capacity = max(2.0, homes.get(p, 0) * 1.25) * state.port_capacity_factor
            congestion = min(1.0, capacity / len(fs))
            for f in fs:
                ok[f] *= congestion
        # A new maker consumes 20 percentage points of utilization per qualified item.
        added: dict[str, int] = defaultdict(int)
        for item, makers in state.produced_at.items():
            original = {f for f, _ in static.original_makers.get(item, ())}
            for f, _ in makers:
                if f not in original:
                    added[f] += 1
        for f, count in added.items():
            spare = max(0.0, 1.0 - utilization(static.facilities.get(f, {})))
            ok[f] *= min(1.0, spare / (0.2 * count))
    avail: dict[str, float] = {}
    for item in static.order or _bottom_up(static):
        value = _production(item, static, state, ok)
        for child in static.children.get(item, ()):
            value = min(value, 1.0 - (1.0 - avail.get(child, 1.0)) * (1.0 - TIER_BUFFER))
        avail[item] = max(value, STOCKPILE_FLOOR) if item in state.stockpiled else value
    plat = {p: avail.get(p, 1.0) for p in static.platforms}
    total = sum(w for _, _, w in static.platforms.values()) or 1.0
    kept = sum(plat[p] * w for p, (_, _, w) in static.platforms.items())
    return Result(loss=max(0.0, 1.0 - kept / total), platform_avail=plat, facility_ok=ok, item_avail=avail)


def _bottom_up(static: Static) -> list[str]:
    """Items ordered so every child comes before its parents (iterative DFS; the BOM is a DAG)."""
    order, seen = [], set()
    for root in static.platforms:
        stack = [(root, False)]
        while stack:
            item, done = stack.pop()
            if done:
                order.append(item)
                continue
            if item in seen:
                continue
            seen.add(item)
            stack.append((item, True))
            stack.extend((c, False) for c in static.children.get(item, ()) if c not in seen)
    return order


def controlled_by(state: State, item: str) -> set[str]:
    return {c.split("|", 1)[0] for c in state.controls if c.split("|", 1)[1] == item}


def _production(item: str, static: Static, state: State, ok: dict[str, float]) -> float:
    blocked = controlled_by(state, item) if state.controls else set()
    makers = state.produced_at.get(item, ())
    # DETACH DELETE removes the maker edges too. Keep the lost share in the denominator so
    # deleting a maker cannot magically increase output at the surviving facilities.
    present = {f for f, _ in makers}
    makers += tuple((f, share) for f, share in static.original_makers.get(item, ()) if f not in present)
    if makers:
        shares = [s if s and s > 0 else 1.0 for _, s in makers]
        prod = sum((0.0 if static.facilities.get(f, {}).get("cc") in blocked else ok.get(f, 0.0)) * s
                   for (f, _), s in zip(makers, shares)) / sum(shares)
    else:
        prod = 1.0
    countries = static.country_share.get(item)
    if countries and blocked:
        total = sum(countries.values()) or 1.0
        prod *= 1.0 - sum(v for cc, v in countries.items() if cc in blocked) / total
    return min(1.0, prod)


def with_changes(state: State, **sets) -> State:
    """A hypothetical state: each keyword adds to that set (closed=..., blocked=..., ...)."""
    return replace(state, **{k: getattr(state, k) | frozenset(v) for k, v in sets.items()})


# ---------------------------------------------------------------------- shared choices (preview == action)


def km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


REROUTE_SPREAD = 3  # exporters are spread over this many alternative ports (no new single point of failure)


def reroute_plan(static: Static, state: State, port: str) -> tuple[list[str], list[str]]:
    """Facilities exporting through `port` and the alternatives they spread over: the open ports with the best
    route factor, same country first, then nearest. Empty when nothing beats the current port."""
    users = sorted(f for f, ps in state.ships_via.items() if port in ps and f in state.facilities)
    here = static.ports.get(port)
    if not users or here is None:
        return [], users
    current = port_factor(static, state, port)
    options = sorted((-port_factor(static, state, p), info["cc"] != here["cc"], km(here, info), p)
                     for p, info in static.ports.items()
                     if p != port and port_factor(static, state, p) > current and p not in state.closed)
    return [o[3] for o in options[:REROUTE_SPREAD]], users


def reroute_assignment(alts: list[str], users: list[str]) -> dict[str, str]:
    """facility -> the alternative port it moves to (round robin, deterministic)."""
    return {f: alts[i % len(alts)] for i, f in enumerate(users)} if alts else {}


def replacement_plan(static: Static, state: State, facility: str, ok: dict[str, float]) -> dict[str, str]:
    """item -> replacement facility, for every item the out-of-action `facility` makes."""
    plan = {}
    for item, makers in state.produced_at.items():
        if any(f == facility for f, _ in makers):
            alt = second_source(static, state, item, ok)
            if alt is not None:
                plan[item] = alt
                if state.capacity_limited:
                    state = replace(state, produced_at={**state.produced_at,
                                    item: state.produced_at.get(item, ()) + ((alt, 50.0),)})
                    ok = evaluate(static, state).facility_ok
    return plan


def second_source(static: Static, state: State, item: str, ok: dict[str, float]) -> str | None:
    """A fully working facility of the same type as the item's makers that does not make it yet,
    preferring allied (NATO/EU) countries, then spare capacity."""
    makers = {f for f, _ in state.produced_at.get(item, ())}
    types = {static.facilities[f]["type"] for f in makers if f in static.facilities}
    best = None
    for f, info in static.facilities.items():
        if f in makers or info["type"] not in types or ok.get(f, 0.0) < 1.0:
            continue
        if state.capacity_limited and utilization(info) > 0.8:
            continue
        key = (info["cc"] not in static.allied, float(info.get("utilization") or 0.0), f)
        best = key if best is None or key < best else best
    return best[2] if best else None


def utilization(info: dict) -> float:
    value = float(info.get("utilization") or 0.0)
    return min(1.0, max(0.0, value / 100 if value > 1 else value))


# ---------------------------------------------------------------------- loading from TuringDB (linear reads)


def _rows(s, cypher: str):
    return s.q(cypher).itertuples(index=False)


def _num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x  # NaN -> 0


def _truthy(v) -> bool:
    """TuringDB returns numpy bools (np.True_ is not True) or, for imported strings, 'true'."""
    return str(v).strip().lower() in ("true", "1", "yes")


def load_static(main) -> Static:
    raw = {str(n): (str(k), str(name), _num(d) * _num(c)) for n, k, name, d, c in _rows(
        main, "MATCH (i:Platform) RETURN i, i.item_id AS k, i.name AS n, i.annual_demand AS d, i.unit_cost_eur AS c")}
    total = sum(v for _, _, v in raw.values()) or 1.0
    plats = {n: (k, name, EQUAL_SHARE / len(raw) + (1 - EQUAL_SHARE) * v / total) for n, (k, name, v) in raw.items()}
    children: dict[str, list[str]] = defaultdict(list)
    for a, b in _rows(main, "MATCH (a)-[:CONTAINS]->(b) RETURN a, b"):
        children[str(a)].append(str(b))
    items = {str(n): (str(k), str(name), label) for label in ITEM_LABELS if label in main.labels
             for n, k, name in _rows(main, f"MATCH (i:{label}) RETURN i, i.item_id AS k, i.name AS n")}
    shares: dict[str, dict[str, float]] = defaultdict(dict)
    for m, cc, sh in _rows(main, "MATCH (m)-[e:PRODUCTION_SHARE]->(c:Country) RETURN m, c.country_code AS cc, "
                                 "e.share_pct AS sh"):
        shares[str(m)][str(cc)] = _num(sh)
    totals = {str(p): _num(n) for p, n in _rows(
        main, "MATCH (pt:Port)<-[:LOADED_AT]-(s:Consignment) RETURN pt, count(s) AS n")}
    port_choke: dict[str, dict[str, float]] = defaultdict(dict)
    for p, c, n in _rows(main, "MATCH (pt:Port)<-[:LOADED_AT]-(s:Consignment)-[:TRANSITED]->(c:Chokepoint) "
                               "RETURN pt, c, count(s) AS n"):
        port_choke[str(p)][str(c)] = _num(n) / max(1.0, totals.get(str(p), 1.0))
    facilities = {str(f): {"facility_id": str(k), "name": str(n), "type": str(t), "cc": str(cc), "lat": _num(la),
                           "lon": _num(lo), "utilization": _num(u)}
                  for f, k, n, t, cc, la, lo, u in _rows(
                      main, "MATCH (f:Facility) RETURN f, f.facility_id AS k, f.name AS n, f.facility_type AS t, "
                            "f.country_code AS cc, f.latitude AS la, f.longitude AS lo, f.capacity_utilization AS u")}
    ports = {str(p): {"port_id": str(k), "name": str(n), "cc": str(cc), "lat": _num(la), "lon": _num(lo)}
             for p, k, n, cc, la, lo in _rows(main, "MATCH (p:Port) RETURN p, p.port_id AS k, p.name AS n, "
                                                    "p.country_code AS cc, p.latitude AS la, p.longitude AS lo")}
    chokes = {str(c): {"waypoint_id": str(k), "name": str(n), "lat": _num(la), "lon": _num(lo)}
              for c, k, n, la, lo in _rows(main, "MATCH (c:Chokepoint) RETURN c, c.waypoint_id AS k, c.name AS n, "
                                                 "c.latitude AS la, c.longitude AS lo")}
    countries, allied = {}, set()
    for c, cc, nato, eu in _rows(main, "MATCH (c:Country) RETURN c, c.country_code AS cc, c.nato_member AS a, "
                                       "c.eu_member AS b"):
        countries[str(cc)] = str(c)
        if _truthy(nato) or _truthy(eu):
            allied.add(str(cc))
    powered = frozenset(str(f) for f, _ in _rows(main, "MATCH (f:Facility)-[:POWERED_BY]->(p:PowerPlant) RETURN f, p"))
    ships_lists: dict[str, set[str]] = defaultdict(set)
    for f, p in _rows(main, "MATCH (f:Facility)-[:SHIPS_VIA]->(p:Port) RETURN f, p"):
        ships_lists[str(f)].add(str(p))
    ships = {f: frozenset(ps) for f, ps in ships_lists.items()}
    original_makers: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for item, fac, share in _rows(main, "MATCH (i)-[e:PRODUCED_AT]->(f:Facility) "
                                "RETURN i, f, e.share_pct AS sh"):
        original_makers[str(item)].append((str(fac), _num(share)))
    static = Static(platforms=plats, children={k: tuple(v) for k, v in children.items()}, items=items,
                    country_share=dict(shares), port_choke=dict(port_choke), facilities=facilities, ports=ports,
                    chokes=chokes, countries=countries, powered_main=powered, ships_main=ships,
                    allied=frozenset(allied),
                    original_makers={i: tuple(m) for i, m in original_makers.items()})
    return replace(static, item_weight=item_weights(static), order=tuple(_bottom_up(static)))


def item_weights(static: Static) -> dict[str, float]:
    """Platform value (demand x cost) that depends on each item, through the bill of materials."""
    weight: dict[str, float] = defaultdict(float)
    for plat, (_, _, w) in static.platforms.items():
        seen, stack = set(), [plat]
        while stack:
            item = stack.pop()
            if item in seen:
                continue
            seen.add(item)
            weight[item] += w
            stack.extend(static.children.get(item, ()))
    return dict(weight)


def _flagged(s, label: str, prop: str, key: str = "") -> set[str]:
    if prop not in s.property_types or label not in s.labels:
        return set()
    col = f", n.{key} AS k" if key else ""
    frame = s.q(f"MATCH (n:{label}) WHERE n.{prop} = true RETURN n{col}")
    return {str(v) for v in (frame["k"] if key else frame["n"])}


def _controls(s) -> set[str]:
    """Export controls are stored on the item as `ops_controls` = 'CHN,RUS' (who restricts its export)."""
    if CONTROLS_PROP not in s.property_types:
        return set()
    out = set()
    for label in ITEM_LABELS[5:]:  # Component, Material, Mineral
        if label not in s.labels:
            continue
        for n, ccs in _rows(s, f"MATCH (n:{label}) WHERE n.{CONTROLS_PROP} <> '' RETURN n, n.{CONTROLS_PROP} AS c"):
            out |= {f"{cc}|{n}" for cc in str(ccs).split(",") if cc}
    return out


def load_state(s) -> State:
    s.refresh_schema()  # earlier edits in this session (a stacked branch's lineage) may add flag properties
    produced: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for i, f, sh in _rows(s, "MATCH (i)-[e:PRODUCED_AT]->(f:Facility) RETURN i, f, e.share_pct AS sh"):
        produced[str(i)].append((str(f), _num(sh)))
    ships: dict[str, list[str]] = defaultdict(list)
    for f, p in _rows(s, "MATCH (f:Facility)-[:SHIPS_VIA]->(p:Port) RETURN f, p"):
        ships[str(f)].append(str(p))
    stock = set()
    for label in ("Component", "Material", "Mineral"):
        stock |= _flagged(s, label, "stockpile")
    from agents.game_rules import read_game

    game = read_game(s)
    return State(
        facilities=frozenset(str(x) for x in s.q("MATCH (f:Facility) RETURN f")["f"]),
        ports=frozenset(str(x) for x in s.q("MATCH (p:Port) RETURN p")["p"]),
        produced_at={k: tuple(v) for k, v in produced.items()},
        ships_via={k: tuple(v) for k, v in ships.items()},
        powered=frozenset(str(f) for f, _ in _rows(s, "MATCH (f:Facility)-[:POWERED_BY]->(p:PowerPlant) RETURN f, p")),
        closed=frozenset(_flagged(s, "Facility", CLOSED_PROP) | _flagged(s, "Port", CLOSED_PROP)),
        blocked=frozenset(_flagged(s, "Chokepoint", CLOSED_PROP)),
        controls=frozenset(_controls(s)),
        stockpiled=frozenset(stock),
        protected=frozenset(_flagged(s, "Facility", "protected") | _flagged(s, "Port", "protected")),
        capacity_limited=bool(game),
        port_capacity_factor=0.8 if game and game.get("event_until", -1) > game["round"] else 1.0,
    )
