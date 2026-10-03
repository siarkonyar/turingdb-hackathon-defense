"""Constants for the theatre build: sources, seeds, radii, synthetic placements, timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_NAME = "theatre"
JSONL_NAME = "theatre.jsonl"  # written to <REPO_ROOT>/data/, where LOAD JSONL looks
SERVER_URL = "http://localhost:6666"

SOURCES = ("power_plants", "supply_chain", "logistics_risk", "drone_swarm", "poledb", "attack_scenarios",
           "supply_chain_deep")
DEEP = "supply_chain_deep"

# Labels renamed in the fused graph: supply_chain_deep's shipments would otherwise mix with the 113k
# logistics_risk Shipments under one label despite a different schema.
RELABELS = {(DEEP, "Shipment"): "Consignment"}

# Labels present in more than one source keep their label; their key value is prefixed with the source.
PREFIXED_KEYS = {("supply_chain", "Supplier"): "supplier_id", ("logistics_risk", "Supplier"): "supplier_id"}

# Original properties renamed because the fused graph reuses the name (TuringDB types are graph-global).
PROPERTY_RENAMES = {
    ("power_plants", "PowerPlant", "source"): "data_source",
    ("attack_scenarios", "Attack", "source"): "data_source",
    ("drone_swarm", "Reading", "timestamp"): "timestep",
    # deep ports / waypoints use lat/lon; theatre (and the OpsMap API) use latitude/longitude
    **{(DEEP, label, short): long for label in ("Port", "Chokepoint", "SeaArea")
       for short, long in (("lat", "latitude"), ("lon", "longitude"))},
}
# Int64 in supply_chain / supply_chain_deep, Double in logistics_risk -> one graph-wide type.
FLOAT_PROPERTIES = frozenset({"lead_time_days"})

SEED = 20261002

POWERED_BY_K = 3
POWERED_BY_MAX_KM = 50.0
NEAR_MAX_KM = 5.0
SITE_JITTER_KM = 1.5
SUPPLIER_JITTER_KM = 5.0
SOURCES_FROM_MIN, SOURCES_FROM_MAX = 1, 3
FACILITY_JITTER_KM = 6.0  # deep facilities are placed at their city centroid plus this much seeded jitter

# Sites: UK and NATO-Europe aerospace towns. SITE01 sits in Greater Manchester, where the
# poledb Locations are, so crimes/people near a critical asset are reachable.
SITES = {
    "SITE01": ("Trafford Park, Manchester", "GBR", 53.468, -2.318),
    "SITE02": ("Warton, Lancashire", "GBR", 53.745, -2.883),
    "SITE03": ("Toulouse-Blagnac", "FRA", 43.629, 1.364),
    "SITE04": ("Hamburg-Finkenwerder", "DEU", 53.535, 9.835),
    "SITE05": ("Seville San Pablo", "ESP", 37.418, -5.893),
    "SITE06": ("Rzeszow-Jasionka", "POL", 50.110, 22.019),
}
PATROL_SITE = "SITE01"

# 40 supplier towns; shuffled onto the sorted supply_chain supplier ids with SEED.
SUPPLIER_TOWNS = (
    ("Bristol", "GBR", 51.45, -2.59), ("Derby", "GBR", 52.92, -1.48), ("Glasgow", "GBR", 55.86, -4.25),
    ("Sheffield", "GBR", 53.38, -1.47), ("Belfast", "GBR", 54.60, -5.93), ("Yeovil", "GBR", 50.94, -2.63),
    ("Bordeaux", "FRA", 44.84, -0.58), ("Marignane", "FRA", 43.42, 5.21), ("Le Bourget", "FRA", 48.95, 2.43),
    ("Nantes", "FRA", 47.22, -1.55), ("Munich", "DEU", 48.14, 11.58), ("Bremen", "DEU", 53.08, 8.80),
    ("Friedrichshafen", "DEU", 47.65, 9.48), ("Stuttgart", "DEU", 48.78, 9.18), ("Turin", "ITA", 45.07, 7.69),
    ("Varese", "ITA", 45.82, 8.83), ("Naples", "ITA", 40.85, 14.27), ("Brindisi", "ITA", 40.63, 17.94),
    ("Seville", "ESP", 37.39, -5.98), ("Barcelona", "ESP", 41.39, 2.17), ("Bilbao", "ESP", 43.26, -2.93),
    ("Mielec", "POL", 50.29, 21.42), ("Warsaw", "POL", 52.23, 21.01), ("Gdansk", "POL", 54.35, 18.65),
    ("Hengelo", "NLD", 52.27, 6.79), ("Eindhoven", "NLD", 51.44, 5.48), ("Gosselies", "BEL", 50.46, 4.45),
    ("Liege", "BEL", 50.63, 5.57), ("Malmo", "SWE", 55.61, 13.00), ("Gothenburg", "SWE", 57.71, 11.97),
    ("Kongsberg", "NOR", 59.67, 9.65), ("Oslo", "NOR", 59.91, 10.75), ("Prague", "CZE", 50.08, 14.44),
    ("Kunovice", "CZE", 49.04, 17.47), ("Bucharest", "ROU", 44.43, 26.10), ("Craiova", "ROU", 44.32, 23.80),
    ("Tampere", "FIN", 61.50, 23.76), ("Odense", "DNK", 55.40, 10.39), ("Steyr", "AUT", 48.04, 14.42),
    ("Evora", "PRT", 38.57, -7.91),
)

# Drone swarm: local x/y units -> metres, projected around PATROL_SITE with (50, 50) at the site.
DRONE_METRES_PER_UNIT = 20.0
DRONE_ORIGIN_XY = (50.0, 50.0)
DRONE_START = datetime(2026, 9, 29, 5, 0, 0, tzinfo=timezone.utc)
DRONE_STEP_SECONDS = 5


def data_dir() -> Path:
    return REPO_ROOT / "data"


def graphs_dir() -> Path:
    return REPO_ROOT / "graphs"
