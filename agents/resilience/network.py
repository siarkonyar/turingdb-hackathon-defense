"""The Dover network as plain immutable Python data, loaded once from main.

Two loaders produce the same structure: `from_corridor()` reads the generator directly (offline tests, no
server) and `from_session()` reads TuringDB. Every number the engine uses comes from these node and edge
properties; nothing is invented here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from graphlib import TopologicalSorter
from types import MappingProxyType
from typing import Any, Iterable, Mapping

NODE_PROPS = (
    "entity_id", "name", "latitude", "longitude", "city", "region", "country_code", "role", "sector",
    "throughput_tonnes_day", "power_demand_mw", "spare_tonnes_day", "spare_service_people", "handling_tonnes_day",
    "mode", "capacity_tonnes_day", "transit_hours", "cold_chain_capable", "pool_kind", "available_units",
    "payload_tonnes", "rotations_day", "stock_tonnes", "generator_fuel_hours", "mobile_generators", "product_id",
    "expires_hours", "recovery_kind", "activation_hours", "duration_hours", "cost_units", "provided_mw",
    "consumes_generators", "consumes_fuel_tonnes_day", "consumes_tonnes_day", "provider_spare_tonnes_day",
    "restores_destroyed_asset", "tonnes", "deadline_hours", "tonnes_day", "priority", "minimum_service_fraction",
    "backlog_allowed", "cold_chain_required", "scenario_kind", "archetype", "displaced_people_capacity",
)
EDGE_PROPS: dict[str, tuple[str, ...]] = {
    "DEPENDS_ON": ("dependency_group", "share"),
    "HAS_RECOVERY": (),
    "REQUIRES": (),
    "STORED_AT": (),
    "USES": ("sequence",),
    "SHIPPED_FROM": (),
    "SHIPPED_TO": (),
    "CARRIES": (),
    "FULFILLS": ("allocation_tonnes",),
    "REQUIRED_BY": (),
    "CAN_USE": ("activation_hours", "handling_hours"),
    "DISABLES": (),
    "PRODUCED_AT": (),
}
LOADED_LABELS = ("Facility", "Port", "PowerPlant", "Chokepoint", "Route", "ResourcePool", "Stockpile",
                 "RecoveryOption", "Consignment", "Demand", "Component", "Scenario", "Platform")


@dataclass(frozen=True)
class Entity:
    eid: str
    label: str
    node_id: str  # TuringDB internal id when live; the entity id offline
    props: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        value = self.props.get(key)
        return default if value is None else value

    def num(self, key: str, default: float = 0.0) -> float:
        return float(self.get(key, default))

    @property
    def name(self) -> str:
        return str(self.get("name", self.eid))

    @property
    def located(self) -> bool:
        return self.props.get("latitude") is not None and self.props.get("longitude") is not None


@dataclass(frozen=True)
class Dependency:
    consumer: str
    provider: str
    group: str
    share: float | None


@dataclass(frozen=True)
class Consignment:
    eid: str
    direction: str  # uk_fr | fr_uk
    sector: str
    tonnes: float
    deadline_hours: float
    origin: str  # exporting inputs facility (SHIPPED_FROM)
    receiver: str  # import customs facility (SHIPPED_TO)
    cold_chain: bool
    priority: int
    handling_hours: float  # from CAN_USE; the same handling assumption is used for every route


@dataclass(frozen=True)
class DemandPoint:
    eid: str
    town: str
    sector: str
    service: str  # REQUIRED_BY facility
    tonnes_day: float
    priority: int
    minimum: float


@dataclass(frozen=True)
class Network:
    entities: Mapping[str, Entity]
    depends: Mapping[str, tuple[Dependency, ...]]  # consumer -> its DEPENDS_ON edges
    dependents: Mapping[str, tuple[Dependency, ...]]  # provider -> edges that name it
    order: tuple[str, ...]  # topological: providers before consumers
    recovery: Mapping[str, tuple[str, ...]]  # asset -> RecoveryOption ids (HAS_RECOVERY)
    requires: Mapping[str, tuple[str, ...]]  # option -> provider ids (REQUIRES)
    stored_at: Mapping[str, str]  # stockpile -> facility
    route_ends: Mapping[str, tuple[str, str]]  # route -> (terminal 0, terminal 1) in USES order
    consignments: tuple[Consignment, ...]
    demands: tuple[DemandPoint, ...]
    disables: Mapping[str, tuple[str, ...]]  # scenario -> initial targets
    capability_of: Mapping[str, str]  # programme facility -> Platform capability

    def entity(self, eid: str) -> Entity:
        try:
            return self.entities[eid]
        except KeyError as exc:
            raise KeyError(f"{eid} is not in the dover graph") from exc

    def option(self, target: str, kind: str) -> Entity | None:
        """The target's RecoveryOption of `kind`, if the graph lists one (never synthesised)."""
        for oid in self.recovery.get(target, ()):
            if self.entities[oid].get("recovery_kind") == kind:
                return self.entities[oid]
        return None

    def town_of(self, eid: str) -> str | None:
        city = self.entities[eid].get("city")
        return None if city is None else town_key(str(city))


def town_key(city: str) -> str:
    return city.lower().replace("-", "_").replace(" ", "_")


def _freeze(mapping: Mapping[str, list]) -> Mapping[str, tuple]:
    return MappingProxyType({k: tuple(v) for k, v in mapping.items()})


Row = tuple[str, str, Mapping[str, Any]]  # (source entity id, target entity id, edge props)


def assemble(nodes: Iterable[tuple[str, str, str, Mapping[str, Any]]],
             edges: Mapping[str, Iterable[Row]]) -> Network:
    """Build a Network from (entity id, label, node id, props) nodes and per-type edge rows."""
    entities = {eid: Entity(eid, label, node_id, MappingProxyType(dict(props))) for eid, label, node_id, props in nodes}
    depends: dict[str, list[Dependency]] = defaultdict(list)
    dependents: dict[str, list[Dependency]] = defaultdict(list)
    for a, b, p in sorted(edges.get("DEPENDS_ON", ()), key=lambda r: (r[0], r[1], str(r[2].get("dependency_group")))):
        share = p.get("share")
        dep = Dependency(a, b, str(p["dependency_group"]), None if share is None else float(share))
        depends[a].append(dep)
        dependents[b].append(dep)
    sorter = TopologicalSorter({c: sorted(d.provider for d in ds) for c, ds in sorted(depends.items())})
    order = tuple(sorter.static_order())  # raises CycleError: the active graph must stay acyclic

    def pairs(kind: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for a, b, _ in sorted(edges.get(kind, ()), key=lambda r: (r[0], r[1])):
            out[a].append(b)
        return out

    uses: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for a, b, p in edges.get("USES", ()):
        uses[a].append((int(p.get("sequence") or 0), b))
    route_ends = {r: (sorted(v)[0][1], sorted(v)[-1][1]) for r, v in uses.items()}
    handling = {a: float(p.get("handling_hours") or 0.0) for a, _, p in edges.get("CAN_USE", ())}
    shipped_from = {a: b for a, b, _ in edges.get("SHIPPED_FROM", ())}
    shipped_to = {a: b for a, b, _ in edges.get("SHIPPED_TO", ())}
    carries = {a: b for a, b, _ in edges.get("CARRIES", ())}
    priority = {e.eid.split(":")[2]: int(e.get("priority", 2)) for e in entities.values() if e.label == "Demand"}
    consignments = []
    for eid, e in sorted(entities.items()):
        if e.label != "Consignment":
            continue
        _, direction, sector = eid.split(":")
        product = entities[carries[eid]]
        consignments.append(Consignment(
            eid, direction, sector, e.num("tonnes"), e.num("deadline_hours"), shipped_from[eid], shipped_to[eid],
            bool(product.get("cold_chain_required", False)), priority.get(sector, 2), handling.get(eid, 0.0)))
    required_by = {a: b for a, b, _ in edges.get("REQUIRED_BY", ())}
    demands = tuple(
        DemandPoint(eid, eid.split(":")[1], eid.split(":")[2], required_by[eid], e.num("tonnes_day"),
                    int(e.get("priority", 2)), e.num("minimum_service_fraction", 0.8))
        for eid, e in sorted(entities.items()) if e.label == "Demand")
    capability_of = {b: a for a, b, _ in edges.get("PRODUCED_AT", ()) if entities[a].label == "Platform"}
    return Network(
        entities=MappingProxyType(entities), depends=_freeze(depends), dependents=_freeze(dependents), order=order,
        recovery=_freeze(pairs("HAS_RECOVERY")), requires=_freeze(pairs("REQUIRES")),
        stored_at=MappingProxyType({a: b for a, b, _ in edges.get("STORED_AT", ())}),
        route_ends=MappingProxyType(route_ends), consignments=tuple(consignments), demands=demands,
        disables=_freeze(pairs("DISABLES")), capability_of=MappingProxyType(capability_of))


def from_corridor(corridor: Any = None) -> Network:
    """Offline loader: the generator's own records (identical to what `build --load` imports)."""
    if corridor is None:
        from datasets.dover.model import build_corridor

        corridor = build_corridor()
    g = corridor.graph
    keep = {i for i, n in enumerate(g.nodes) if n.labels[0] in LOADED_LABELS}
    eid = {i: str(n.props["entity_id"]) for i, n in enumerate(g.nodes)}
    nodes = [(eid[i], g.nodes[i].labels[0], eid[i], {k: g.nodes[i].props.get(k) for k in NODE_PROPS})
             for i in sorted(keep)]
    edges: dict[str, list[Row]] = defaultdict(list)
    for e in g.edges:
        if e.edge_type in EDGE_PROPS and e.start in keep and e.end in keep:
            edges[e.edge_type].append((eid[e.start], eid[e.end], {k: e.props.get(k) for k in EDGE_PROPS[e.edge_type]}))
    return assemble(nodes, edges)


def from_session(session: Any) -> Network:
    """Live loader over an api Session checked out on main (read-only)."""
    from api.nodes import clean

    props = session.has_props(NODE_PROPS)
    nodes = []
    for label in LOADED_LABELS:
        cols = ", ".join(f"n.`{p}` AS `{p}`" for p in props)
        frame = session.q(f"MATCH (n:{label}) RETURN n, {cols}")
        for row in frame.to_dict("records"):
            values = {p: clean(row.get(p)) for p in props}
            nodes.append((str(values["entity_id"]), label, str(row["n"]), values))
    edges: dict[str, list[Row]] = {}
    for kind, eprops in EDGE_PROPS.items():
        known = session.has_props(eprops)
        cols = "".join(f", e.`{p}` AS `{p}`" for p in known)
        frame = session.q(f"MATCH (a)-[e:{kind}]->(b) RETURN a.entity_id AS a, b.entity_id AS b{cols}")
        edges[kind] = [(str(r["a"]), str(r["b"]), {p: clean(r.get(p)) for p in known})
                       for r in frame.to_dict("records")]
    loaded = {n[0] for n in nodes}
    edges = {k: [r for r in rows if r[0] in loaded and r[1] in loaded] for k, rows in edges.items()}
    return assemble(nodes, edges)
