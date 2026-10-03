"""Synthetic corridor topology, separate from every bundled source graph.

SUPPLIES is a display projection. DEPENDS_ON, deliveries and dormant recovery
options are the authoritative input for a future resource-aware scenario engine.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from dataclasses import dataclass, field

from fusion.graph_model import GraphBuilder

SOURCE = "dover_synthetic_v1"
SEED = 20261003
BOUNDS = (-0.6, 48.7, 3.15, 51.7)
# Town centroids are illustrative placement anchors, never actual asset positions.
PLACES = (
    ("london", "London", "London", "GBR", 51.507, -0.128),
    ("croydon", "Croydon", "London", "GBR", 51.372, -0.100),
    ("dartford", "Dartford", "Kent", "GBR", 51.446, 0.219),
    ("gravesend", "Gravesend", "Kent", "GBR", 51.442, 0.370),
    ("medway", "Medway", "Kent", "GBR", 51.389, 0.540),
    ("maidstone", "Maidstone", "Kent", "GBR", 51.272, 0.529),
    ("sittingbourne", "Sittingbourne", "Kent", "GBR", 51.341, 0.734),
    ("canterbury", "Canterbury", "Kent", "GBR", 51.280, 1.078),
    ("ashford", "Ashford", "Kent", "GBR", 51.146, 0.875),
    ("folkestone", "Folkestone", "Kent", "GBR", 51.082, 1.175),
    ("dover", "Dover", "Kent", "GBR", 51.127, 1.313),
    ("deal", "Deal", "Kent", "GBR", 51.223, 1.402),
    ("newhaven", "Newhaven", "Sussex", "GBR", 50.794, 0.055),
    ("calais", "Calais", "Coastal France", "FRA", 50.951, 1.858),
    ("dunkirk", "Dunkirk", "Coastal France", "FRA", 51.034, 2.377),
    ("boulogne", "Boulogne", "Coastal France", "FRA", 50.726, 1.614),
    ("saint_omer", "Saint-Omer", "Northern France", "FRA", 50.749, 2.252),
    ("arras", "Arras", "Northern France", "FRA", 50.291, 2.778),
    ("amiens", "Amiens", "Northern France", "FRA", 49.894, 2.295),
    ("abbeville", "Abbeville", "Northern France", "FRA", 50.106, 1.833),
    ("dieppe", "Dieppe", "Normandy", "FRA", 49.922, 1.077),
    ("rouen", "Rouen", "Normandy", "FRA", 49.443, 1.099),
    ("beauvais", "Beauvais", "Paris Corridor", "FRA", 49.430, 2.081),
    ("creil", "Creil", "Paris Corridor", "FRA", 49.260, 2.473),
    ("paris", "Paris", "Paris", "FRA", 48.857, 2.352),
    ("saint_denis", "Saint-Denis", "Paris", "FRA", 48.936, 2.357),
)
SECTORS = (
    ("medical", "Medical consumables", "medical", 2.0, 24.0, True),
    ("food", "Food packs", "food", 12.0, 48.0, False),
    ("water", "Water treatment supplies", "water", 8.0, 24.0, False),
    ("fuel", "Packaged generator fuel", "fuel", 20.0, 36.0, False),
    ("repair", "Vehicle repair kits", "maintenance", 6.0, 72.0, False),
    ("power", "Electrical repair modules", "energy", 5.0, 24.0, False),
    ("comms", "Communications spares", "communications", 1.5, 12.0, False),
    ("shelter", "Emergency shelter packs", "shelter", 10.0, 48.0, False),
    ("cold", "Temperature-controlled medicines", "medical", 1.0, 12.0, True),
    ("sanitation", "Sanitation consumables", "sanitation", 4.0, 36.0, False),
)


@dataclass
class Corridor:
    graph: GraphBuilder = field(default_factory=GraphBuilder)
    ids: dict[str, int] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(SEED))
    place: dict[str, tuple] = field(default_factory=lambda: {p[0]: p for p in PLACES})

    def node(self, key: str, label: str, name: str, town: str | None = None, **props) -> str:
        base = dict(entity_id=key, name=name, source=SOURCE, synthetic=True,
                    status="operational", **props)
        if town:
            _, city, region, country, lat, lon = self.place[town]
            base.update(city=city, place=city, region=region, country_code=country,
                        latitude=round(lat + self.rng.uniform(-0.018, 0.018), 6),
                        longitude=round(lon + self.rng.uniform(-0.025, 0.025), 6),
                        geo_method="illustrative_centroid_jitter", geo_synthetic=True)
        key_prop = {"Facility": "facility_id", "Port": "port_id", "PowerPlant": "gppd_idnr",
                    "Chokepoint": "waypoint_id", "Platform": "platform_id",
                    "Consignment": "consignment_id"}.get(label)
        if key_prop:
            base[key_prop] = key
        self.ids[key] = self.graph.add_node((label,), base, key=(label, key))
        return key

    def edge(self, src: str, dst: str, kind: str, **props) -> None:
        self.graph.add_edge(self.ids[src], self.ids[dst], kind, dict(source=SOURCE, synthetic=True, **props))

    def depends(self, consumer: str, provider: str, resource: str, **props) -> None:
        self.edge(consumer, provider, "DEPENDS_ON", resource=resource, dependency_group=resource,
                  logic="required", active=True, **props)

    def facility(self, key: str, role: str, town: str, sector: str = "infrastructure", **props) -> str:
        city = self.place[town][1]
        self.node(key, "Facility", f"Exercise {city} {role.replace('_', ' ')} ({sector})", town,
                  role=role, sector=sector,
                  throughput_tonnes_day=1600.0 if role in ("road_hub", "rail_hub", "customs_hub") else 200.0,
                  power_demand_mw=0.3, spare_service_people=100, **props)
        self.edge(key, f"place:{town}", "LOCATED_IN_PLACE")
        self.edge(key, f"country:{self.place[town][3]}", "LOCATED_IN")
        self.edge(key, f"company:{sector}", "OPERATED_BY")
        return key

    def recovery(self, target: str, kind: str, providers: list[str], capacity: float,
                 delay: float, duration: float = 168.0, **props) -> str:
        key = f"recovery:{target}:{kind}"
        self.node(key, "RecoveryOption", f"{kind.replace('_', ' ').title()} for {target}",
                  recovery_kind=kind, active=False, capacity_tonnes_day=float(capacity),
                  activation_hours=float(delay), duration_hours=float(duration),
                  cost_units=float(2 + delay / 6), allocation_rule="shared_pool_no_double_counting", **props)
        self.edge(target, key, "HAS_RECOVERY")
        for provider in providers:
            self.edge(key, provider, "REQUIRES", quantity=1.0)
        return key


def build_corridor() -> Corridor:
    c = Corridor()
    for country, name in (("GBR", "United Kingdom"), ("FRA", "France")):
        c.node(f"country:{country}", "Country", name, country_code=country,
               nato_member=True, eu_member=country == "FRA")
    for sector in ("infrastructure", *(s[0] for s in SECTORS)):
        c.node(f"company:{sector}", "Company", f"Exercise {sector.title()} Cooperative")
    for key, name, region, country, lat, lon in PLACES:
        c.node(f"place:{key}", "Place", name, key)
        c.edge(f"place:{key}", f"country:{country}", "IN_COUNTRY")
        if f"region:{region}" not in c.ids:
            c.node(f"region:{region}", "Region", region)
        c.edge(f"place:{key}", f"region:{region}", "IN_REGION")
        c.node(f"grid:{key}", "PowerPlant", f"Exercise {name} grid supply", key,
               capacity_mw=150.0, primary_fuel="synthetic_mixed", power_domain=region)
        for role in ("substation", "water_works", "telecom_exchange", "fuel_depot", "backup_depot"):
            c.facility(f"infra:{key}:{role}", role, key)
        c.depends(f"infra:{key}:substation", f"grid:{key}", "electricity")
        c.edge(f"infra:{key}:substation", f"grid:{key}", "POWERED_BY")
        for role in ("water_works", "telecom_exchange", "fuel_depot"):
            c.depends(f"infra:{key}:{role}", f"infra:{key}:substation", "electricity")
            c.edge(f"infra:{key}:{role}", f"grid:{key}", "POWERED_BY")
        # Fuel depots can pump during a power outage after mobile power is allocated.
        c.depends(f"infra:{key}:water_works", f"infra:{key}:fuel_depot", "maintenance_fuel")
        c.node(f"stock:{key}", "Stockpile", f"Exercise {name} emergency reserve", key,
               stock_tonnes=120.0, generator_fuel_hours=72.0, battery_hours=8.0,
               mobile_generators=3, mobile_water_units=2)
        c.edge(f"stock:{key}", f"infra:{key}:backup_depot", "STORED_AT")
        c.node(f"crew:{key}", "ResourcePool", f"Exercise {name} repair teams", key,
               pool_kind="repair_teams", available_units=4, daily_work_hours=32.0)
    _transport(c)
    _services(c)
    _recoveries(c)
    _scenarios(c)
    payload = json.dumps(dict(nodes=[asdict(n) for n in c.graph.nodes],
                              edges=[asdict(e) for e in c.graph.edges]), sort_keys=True)
    c.graph.nodes[c.ids["dataset:dover"]].props["build_fingerprint"] = hashlib.sha256(payload.encode()).hexdigest()
    return c


def _transport(c: Corridor) -> None:
    c.node("chokepoint:dover", "Chokepoint", "Dover Strait", "dover", type="maritime_chokepoint")
    # Override jitter: this is a sea marker, not a port or an asset coordinate.
    c.graph.nodes[c.ids["chokepoint:dover"]].props.update(latitude=51.02, longitude=1.52)
    for town in ("dover", "calais", "dunkirk", "newhaven", "dieppe"):
        c.node(f"port:{town}", "Port", f"Exercise {c.place[town][1]} freight port", town,
               handling_tonnes_day=1600.0)
        c.depends(f"port:{town}", f"infra:{town}:substation", "electricity")
        c.depends(f"port:{town}", f"infra:{town}:telecom_exchange", "communications")
    for town in ("london", "ashford", "beauvais", "paris"):
        c.facility(f"airport:{town}", "cargo_airport", town)
        c.depends(f"airport:{town}", f"infra:{town}:substation", "electricity")
        c.depends(f"airport:{town}", f"infra:{town}:fuel_depot", "aviation_fuel")
        c.depends(f"airport:{town}", f"infra:{town}:telecom_exchange", "communications")
        c.node(f"aircraft:{town}", "ResourcePool", f"Exercise {town.title()} cargo aircraft pool", town,
               pool_kind="cargo_aircraft", available_units=4, payload_tonnes=16.0,
               rotations_day=1.0, cold_chain_capable=True)
    for town in ("folkestone", "calais"):
        c.facility(f"tunnel:{town}", "tunnel_terminal", town)
        c.depends(f"tunnel:{town}", f"infra:{town}:substation", "electricity")
        c.depends(f"tunnel:{town}", f"infra:{town}:telecom_exchange", "communications")
    for key, *_ in PLACES:
        for role in ("road_hub", "rail_hub", "customs_hub"):
            c.facility(f"transport:{key}:{role}", role, key)
            c.depends(f"transport:{key}:{role}", f"infra:{key}:substation", "electricity")
            c.depends(f"transport:{key}:{role}", f"infra:{key}:telecom_exchange", "communications")
        c.depends(f"transport:{key}:road_hub", f"infra:{key}:fuel_depot", "vehicle_fuel")
    routes = (
        ("dover_calais", "sea", "dover", "calais", 1600., 8., True),
        ("dover_dunkirk", "sea", "dover", "dunkirk", 500., 10., True),
        ("western_channel", "sea", "newhaven", "dieppe", 240., 18., False),
        ("tunnel", "rail", "folkestone", "calais", 320., 6., False),
        ("london_paris_air", "air", "london", "paris", 64., 4., False),
        ("kent_beauvais_air", "air", "ashford", "beauvais", 64., 5., False),
    )
    for key, mode, src, dst, capacity, hours, strait in routes:
        route = c.node(f"route:{key}", "Route", f"Exercise {key.replace('_', ' ')} corridor",
                       mode=mode, capacity_tonnes_day=capacity, transit_hours=hours,
                       bidirectional=True, capacity_shared_directions=True, cold_chain_capable=True)
        prefix = {"sea": "port", "rail": "tunnel", "air": "airport"}[mode]
        for order, town in enumerate((src, dst)):
            c.edge(route, f"{prefix}:{town}", "USES", sequence=order)
            c.depends(route, f"{prefix}:{town}", f"terminal_{order}")
            c.depends(route, f"transport:{town}:road_hub", f"last_mile_{order}")
        if strait:
            c.depends(route, "chokepoint:dover", "sea_access")
        if mode == "air":
            for town in (src, dst):
                c.depends(route, f"aircraft:{town}", "aircraft_" + town)



def _services(c: Corridor) -> None:
    for sector, product_name, service, tonnes, deadline, cold in SECTORS:
        c.node(f"product:{sector}", "Component", f"Exercise {product_name}",
               product_class=sector, unit="tonnes", cold_chain_required=cold,
               shelf_life_hours=72.0 if cold else 720.0, splittable=True)
        for direction, source_towns, recipient_country in (
            ("uk_fr", ("london", "maidstone", "medway"), "FRA"),
            ("fr_uk", ("paris", "rouen", "amiens"), "GBR"),
        ):
            source_town = source_towns[SECTORS.index((sector, product_name, service, tonnes, deadline, cold)) % 3]
            dst_town = "calais" if direction == "uk_fr" else "dover"
            src_port = "dover" if direction == "uk_fr" else "calais"
            prefix = f"chain:{direction}:{sector}"
            inland = "amiens" if direction == "uk_fr" else "ashford"
            stages = (("inputs", source_town), ("import_customs", dst_town),
                      ("inbound_sorting", dst_town), ("processing", inland),
                      ("manufacturing", inland), ("quality_release", inland),
                      ("packing", inland), ("regional_staging", inland),
                      ("freight_dispatch", inland))
            previous = None
            for stage, town in stages:
                fid = c.facility(f"{prefix}:{stage}", stage, town, sector)
                if previous:
                    c.edge(previous, fid, "SUPPLIES", annual_volume=3650.0, product_id=f"product:{sector}")
                    c.depends(fid, previous, "material_input")
                c.depends(fid, f"infra:{town}:substation", "electricity")
                c.edge(fid, f"grid:{town}", "POWERED_BY")
                c.depends(fid, f"infra:{town}:telecom_exchange", "communications")
                if cold or sector in ("medical", "water", "sanitation"):
                    c.depends(fid, f"infra:{town}:water_works", "process_water")
                if stage == "freight_dispatch":
                    c.depends(fid, f"transport:{town}:road_hub", "road_access")
                if stage == "import_customs":
                    c.depends(fid, "route:dover_calais", "crossing")
                    c.depends(fid, f"transport:{town}:customs_hub", "customs_release")
                previous = fid
            root = f"{prefix}:inputs"
            c.edge(f"product:{sector}", f"{prefix}:manufacturing", "PRODUCED_AT", share=50.0)
            # Existing display cascade seeds exporting inputs and walks the 8 remaining stages.
            consignment = c.node(f"consignment:{direction}:{sector}", "Consignment",
                                 f"Exercise recurring {direction} {product_name}",
                                 tonnes=tonnes * 13 * 0.6,
                                 departure_hours=0.0, deadline_hours=deadline, recurring_interval_hours=24.0,
                                 delivery_status="scheduled", splittable=True)
            c.edge(consignment, root, "SHIPPED_FROM")
            c.edge(consignment, f"{prefix}:import_customs", "SHIPPED_TO")
            c.edge(consignment, f"port:{src_port}", "LOADED_AT")
            c.edge(consignment, f"port:{dst_town}", "UNLOADED_AT")
            c.edge(consignment, "chokepoint:dover", "TRANSITED")
            c.edge(consignment, "route:dover_calais", "ROUTED_VIA", active=True)
            c.edge(consignment, f"product:{sector}", "CARRIES")
            for route in ("western_channel", "tunnel", "london_paris_air", "kent_beauvais_air"):
                c.edge(consignment, f"route:{route}", "CAN_USE", active=False,
                       activation_hours=4.0 if "air" in route else 8.0,
                       handling_hours=2.0, cost_multiplier=5.0 if "air" in route else 1.5)
            for town, city, _, country, *_ in PLACES:
                if country != recipient_country:
                    continue
                dist = c.facility(f"local:{town}:{sector}:distribution", "distribution", town, sector)
                reserve = c.facility(f"local:{town}:{sector}:producer", "local_producer", town, sector, spare_tonnes_day=20.0)
                endpoint_role = {"medical": "hospital", "cold": "medical_cold_store", "food": "feeding_centre",
                                 "water": "water_service", "fuel": "generator_service", "repair": "repair_workshop",
                                 "power": "grid_repair_service", "comms": "communications_service",
                                 "shelter": "shelter_centre", "sanitation": "sanitation_service"}[sector]
                endpoint = c.facility(f"local:{town}:{sector}:service", endpoint_role, town, sector,
                                      stock_cover_hours=12.0 if cold else 24.0,
                                      beneficiary="fictional_NATO_support_and_civilian_services")
                c.edge(previous, dist, "SUPPLIES", annual_volume=tonnes * 365 * 0.6,
                       product_id=f"product:{sector}")
                c.edge(reserve, dist, "SUPPLIES", annual_volume=tonnes * 365 * 0.4,
                       product_id=f"product:{sector}")
                c.depends(dist, previous, "material_input", share=0.6)
                # Same group is share-weighted, unlike required utility groups.
                c.depends(dist, reserve, "material_input", share=0.4)
                c.edge(dist, endpoint, "SUPPLIES", annual_volume=tonnes * 365,
                       product_id=f"product:{sector}")
                c.depends(endpoint, dist, "consumables")
                for fid in (dist, reserve, endpoint):
                    c.depends(fid, f"infra:{town}:substation", "electricity")
                    c.edge(fid, f"grid:{town}", "POWERED_BY")
                    c.depends(fid, f"infra:{town}:telecom_exchange", "communications")
                if sector in ("medical", "cold", "food", "sanitation"):
                    c.depends(endpoint, f"infra:{town}:water_works", "water")
                demand = c.node(f"demand:{town}:{sector}", "Demand", f"Exercise {city} {product_name} daily demand",
                                tonnes_day=tonnes, deadline_hours=deadline,
                                priority=1 if sector in ("medical", "cold", "water") else 2,
                                minimum_service_fraction=0.8, backlog_allowed=sector in ("repair", "shelter"))
                c.edge(demand, endpoint, "REQUIRED_BY")
                c.edge(demand, f"product:{sector}", "NEEDS")
                c.edge(consignment, demand, "FULFILLS", allocation_tonnes=tonnes * 0.6)
    for town, *_ in PLACES:
        for sector, target, kind in (("fuel", f"infra:{town}:fuel_depot", "REPLENISHES"),
                                     ("power", f"grid:{town}", "REPAIRS"),
                                     ("comms", f"infra:{town}:telecom_exchange", "REPAIRS")):
            c.edge(f"local:{town}:{sector}:service", target, kind,
                   lead_time_hours=12.0, active=False)
    # Shared endpoint programmes give branching/converging, cross-sector dependencies.
    for town, city, *_ in PLACES:
        for role, sectors in (("nato_support_unit", ("medical", "food", "fuel", "repair", "comms")),
                              ("military_hospital", ("medical", "cold", "water", "power", "sanitation")),
                              ("civil_emergency_centre", ("shelter", "food", "water", "comms", "fuel"))):
            endpoint = c.facility(f"mission:{town}:{role}", role, town,
                                  beneficiary="fictional_exercise_organisation", minimum_service_fraction=0.8)
            c.depends(endpoint, f"infra:{town}:substation", "electricity")
            c.edge(endpoint, f"grid:{town}", "POWERED_BY")
            for sector in sectors:
                service = f"local:{town}:{sector}:service"
                c.depends(endpoint, service, sector)
                c.edge(service, endpoint, "SUPPLIES", annual_volume=365.0, product_id=f"product:{sector}")
            capability = c.node(f"capability:{town}:{role}", "Platform", f"Exercise {city} {role.replace('_', ' ')} capability",
                                archetype="medical_support" if "hospital" in role else "humanitarian_logistics",
                                annual_demand=1.0, unit_cost=1.0)
            c.edge(capability, endpoint, "PRODUCED_AT", share=100.0)
            c.depends(capability, endpoint, "service")
            c.edge(endpoint, f"place:{town}", "SERVES")


def _recoveries(c: Corridor) -> None:
    facilities = [n.props["entity_id"] for n in c.graph.nodes if n.labels == ("Facility",)]
    for fid in facilities:
        node = c.graph.nodes[c.ids[fid]]
        town = next(p[0] for p in PLACES if p[1] == node.props["city"])
        sector = str(node.props["sector"])
        c.recovery(fid, "mobile_power", [f"stock:{town}", f"infra:{town}:fuel_depot"],
                   80., 2., 72., resource_group="electricity", provided_mw=2.0,
                   consumes_generators=1, consumes_fuel_tonnes_day=0.5,
                   restores_destroyed_asset=False)
        c.recovery(fid, "repair", [f"crew:{town}", f"stock:{town}"], 200., 24.,
                   resource_group="asset_condition", consumes_repair_teams=1,
                   restores_destroyed_asset=False)
        # An independent-region site supports continuity even if the target is destroyed.
        candidates = [p[0] for p in PLACES if p[2] != node.props["region"]
                      and p[3] == node.props["country_code"]]
        backup_town = candidates[sum(map(ord, fid)) % len(candidates)]
        role = str(node.props["role"])
        if role in ("military_hospital", "nato_support_unit", "civil_emergency_centre"):
            backup = f"mission:{backup_town}:{role}"
        elif role == "hospital":
            backup = f"local:{backup_town}:{sector}:service"
        elif sector != "infrastructure":
            backup = f"local:{backup_town}:{sector}:producer"
        elif role in ("water_works", "telecom_exchange", "fuel_depot", "substation", "backup_depot"):
            backup = f"infra:{backup_town}:{role}"
        elif role in ("road_hub", "rail_hub", "customs_hub"):
            backup = f"transport:{backup_town}:{role}"
        else:
            backup = f"infra:{backup_town}:backup_depot"
        c.recovery(fid, "relocate_service" if str(node.props["role"]) in (
            "military_hospital", "nato_support_unit", "civil_emergency_centre", "hospital") else "second_source",
            [backup, f"transport:{backup_town}:road_hub"], 20., 12.,
            resource_group="service_continuity", provider_spare_tonnes_day=20.0,
            restores_destroyed_asset=False, displaced_people_capacity=100)
    for town in ("dover", "calais", "dunkirk", "newhaven", "dieppe"):
        other = "newhaven" if c.place[town][3] == "GBR" else "dieppe"
        if town == other:
            other = "dover" if other == "newhaven" else "calais"
        c.recovery(f"port:{town}", "alternate_port", [f"port:{other}", "route:western_channel"], 240., 8.,
                   resource_group="port_access", restores_destroyed_asset=False)
        c.recovery(f"port:{town}", "mobile_power", [f"stock:{town}", f"infra:{town}:fuel_depot"], 80., 2., 72.,
                   resource_group="electricity", provided_mw=2.0, consumes_generators=1,
                   restores_destroyed_asset=False)
    for town, *_ in PLACES:
        c.recovery(f"grid:{town}", "islanded_generation", [f"stock:{town}", f"infra:{town}:fuel_depot"],
                   80., 4., 72., resource_group="electricity", provided_mw=2.0, consumes_generators=1,
                   restores_destroyed_asset=False)
    for target in ("chokepoint:dover", "route:dover_calais", "route:dover_dunkirk"):
        for route, delay, capacity in (("tunnel", 8., 320.), ("western_channel", 8., 240.),
                                       ("london_paris_air", 4., 64.), ("kent_beauvais_air", 4., 64.)):
            c.recovery(target, f"reroute_{route}", [f"route:{route}"], capacity, delay,
                       resource_group="crossing", restores_destroyed_asset=False)
    for town, *_ in PLACES:
        for sector, _, _, tonnes, *_ in SECTORS:
            c.node(f"reserve:{town}:{sector}", "Stockpile", f"Exercise {town} {sector} buffer", town,
                   stock_tonnes=tonnes * 2., product_id=f"product:{sector}", expires_hours=72.0)
            c.edge(f"reserve:{town}:{sector}", f"local:{town}:{sector}:distribution", "STORED_AT")
            c.recovery(f"local:{town}:{sector}:service", "release_stock",
                       [f"reserve:{town}:{sector}"], tonnes, 1., 48.,
                       resource_group="consumables", consumes_tonnes_day=tonnes,
                       restores_destroyed_asset=False)


def _scenarios(c: Corridor) -> None:
    examples = (
        ("strait_closure", "Dover Strait maritime closure", "closure", "maritime access", 72.,
         ["chokepoint:dover"]),
        ("kent_power", "Kent-wide grid outage", "power_outage", "electricity", 48.,
         [f"grid:{p[0]}" for p in PLACES if p[2] == "Kent"]),
        ("london_loss", "London-area catastrophic infrastructure loss", "regional_loss", "all physical services", 168.,
         [n.props["entity_id"] for n in c.graph.nodes if n.props.get("region") == "London"
          and n.labels[0] in ("Facility", "PowerPlant", "Stockpile", "ResourcePool")]),
        ("calais_port", "Calais freight terminal outage", "closure", "port handling", 36., ["port:calais"]),
        ("tunnel_loss", "Tunnel terminal outage", "closure", "rail access", 24., ["tunnel:folkestone"]),
        ("paris_power", "Paris-area grid outage", "power_outage", "electricity", 48.,
         ["grid:paris", "grid:saint_denis"]),
        ("fuel_shortage", "Kent generator fuel depot shortage", "resource_shortage", "fuel", 72.,
         [f"infra:{p[0]}:fuel_depot" for p in PLACES if p[2] == "Kent"]),
        ("comms_loss", "Cross-border customs communications outage", "closure", "communications", 12.,
         ["infra:dover:telecom_exchange", "infra:calais:telecom_exchange"]),
        ("combined", "Maritime closure during Kent grid outage", "combined", "multiple", 72.,
         ["chokepoint:dover", *[f"grid:{p[0]}" for p in PLACES if p[2] == "Kent"]]),
    )
    for key, name, kind, resource, duration, targets in examples:
        scenario = c.node(f"scenario:{key}", "Scenario", name,
                          scenario_kind=kind, affected_resource=resource, start_hours=0.0,
                          duration_hours=duration, active=False,
                          description="Illustrative event definition only; no changes applied to baseline")
        for target in targets:
            c.edge(scenario, target, "DISABLES", initial_loss_fraction=1.0)
    c.node("dataset:dover", "Dataset", "London-Dover-Paris synthetic resilience corridor",
           schema_version="1.0", seed=SEED, centre_latitude=51.02, centre_longitude=1.52,
           west=BOUNDS[0], south=BOUNDS[1], east=BOUNDS[2], north=BOUNDS[3],
           assumptions="All organisations, facilities, capacities and demands are fictional exercise data",
           dependency_semantics="Required utility groups; share-weighted material_input; dormant recovery options")
