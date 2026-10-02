"""Hand-written synthetic scenario for the mock fixtures. Everything here is fake except the
power plants, which generate.py pulls from the real `power_plants` graph.

Report text uses placeholders resolved by generate.py:
    {FEED}  largest power plant feeding SITE01      {SUPX} supplier whose parts reach most sites
    {SUPX_PLACE} that supplier's town
"""

from __future__ import annotations

from datetime import datetime, timezone

SEED = 20261002
TIMELINE_START = datetime(2026, 9, 29, 5, 0, 0, tzinfo=timezone.utc)
DRONE_STEPS = 1000
DRONE_STEP_SECONDS = 18  # 1000 steps -> 05:00Z..10:00Z
DRONE_TRACK_EVERY = 5  # keep every 5th reading (90 s) in the fixture
DRONE_COUNT = 20

POWERED_BY_K = 3
POWERED_BY_MAX_KM = 50.0
PART_COUNT = 300
CRIME_COUNTS = {"SITE01": 320, "SITE02": 60}
CRIME_RADIUS_KM = 5.0

SITES = (
    ("SITE01", "Trafford Park, Manchester", "GBR", 53.468, -2.318),
    ("SITE02", "Warton, Lancashire", "GBR", 53.745, -2.883),
    ("SITE03", "Toulouse-Blagnac", "FRA", 43.629, 1.364),
    ("SITE04", "Hamburg-Finkenwerder", "DEU", 53.535, 9.835),
    ("SITE05", "Seville San Pablo", "ESP", 37.418, -5.893),
    ("SITE06", "Rzeszow-Jasionka", "POL", 50.110, 22.019),
)
PATROL_SITE = "SITE01"

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

PART_FAMILIES = ("Actuator", "Avionics LRU", "Bearing", "Composite panel", "Fastener kit", "Harness",
                 "Hydraulic pump", "Seal kit", "Sensor", "Valve")
CRIME_TYPES = ("Anti-social behaviour", "Burglary", "Criminal damage and arson", "Drugs",
               "Public order", "Theft from the person", "Vehicle crime", "Violence and sexual offences")

# Attack scenarios per AssetType (approximate counts; the live graph derives them from attack_scenarios).
ATTACKS_BY_ASSET_TYPE = {"ICS_SCADA": 1180, "OT_NETWORK": 2410, "ERP": 930, "CORPORATE_IT": 3960,
                         "SW_SUPPLY_CHAIN": 1460, "LOGISTICS_IT": 690, "PHYSICAL_ACCESS": 410}
RUNS_BY_LABEL = {"Site": ("ICS_SCADA", "OT_NETWORK", "ERP", "CORPORATE_IT", "PHYSICAL_ACCESS"),
                 "Supplier": ("ERP", "CORPORATE_IT", "SW_SUPPLY_CHAIN")}

# (report_id, batch, HH:MM, source_type, confidence, claim, subject, text, contradicts)
# subject: FEED | SUPX | SITE01 | SITE02
REPORT_SCRIPT = (
    ("R-001", 1, "05:06", "drone", 0.55, "activity", "SITE01",
     "UAS-07 EO/IR: two vehicles stationary at the north perimeter fence, engines running.", None),
    ("R-002", 1, "05:18", "drone", 0.60, "activity", "FEED",
     "UAS-03: personnel observed near the {FEED} substation, no identification.", None),
    ("R-003", 1, "05:31", "OSINT", 0.40, "activity", "SITE01",
     "Local social media: multiple posts report drones over Trafford Park industrial estate.", None),
    ("R-004", 1, "05:44", "HUMINT", 0.50, "activity", "SUPX",
     "Source: unscheduled night shipment leaving {SUPX} ({SUPX_PLACE}).", None),
    ("R-005", 2, "06:02", "SIGINT", 0.70, "damaged", "FEED",
     "Grid telemetry: {FEED} output dropped to zero at 06:01Z.", None),
    ("R-006", 2, "06:09", "drone", 0.75, "damaged", "FEED",
     "UAS-11: thermal bloom and smoke plume over the {FEED} turbine hall.", None),
    ("R-007", 2, "06:15", "OSINT", 0.60, "damaged", "FEED",
     "Regional news: explosion heard near {FEED}; emergency services en route.", None),
    ("R-008", 2, "06:31", "HUMINT", 0.45, "operational", "SITE01",
     "Site security: SITE01 running on backup generators, production continuing.", None),
    ("R-009", 2, "06:48", "drone", 0.55, "activity", "SITE01",
     "UAS-02: fuel bowser convoy entering the SITE01 south gate.", None),
    ("R-010", 3, "07:35", "SIGINT", 0.65, "disrupted", "SUPX",
     "Intercepted logistics traffic: {SUPX} shipments held at depot.", None),
    ("R-011", 3, "07:52", "OSINT", 0.50, "disrupted", "SUPX",
     "Freight tracker: no departures from {SUPX_PLACE} since 06:00Z.", None),
    ("R-012", 3, "08:10", "HUMINT", 0.40, "activity", "SITE02",
     "Warton site reports a precautionary lockdown after a suspicious package.", None),
    ("R-013", 3, "08:25", "drone", 0.60, "activity", "SITE01",
     "UAS-14: unidentified quadcopter loitering 400 m west of SITE01.", None),
    ("R-014", 4, "09:05", "HUMINT", 0.55, "operational", "FEED",
     "Plant engineer: {FEED} tripped on a grid fault, no structural damage; restart expected 12:00Z.", "R-006"),
    ("R-015", 4, "09:20", "SIGINT", 0.50, "operational", "FEED",
     "Grid telemetry: {FEED} resynchronising at 18% output.", "R-005"),
    ("R-016", 4, "09:34", "OSINT", 0.35, "damaged", "FEED",
     "Imagery analyst: burn scar visible on the {FEED} transformer yard.", None),
    ("R-017", 4, "09:50", "drone", 0.60, "activity", "SITE01",
     "UAS-05: perimeter clear; vehicles seen at 05:06Z have departed.", None),
)

# Competing intelligence hypotheses: each is a branch that removes one subject and lets the cascade run.
HYPOTHESES = (
    ("1", "H1 · Feed plant destroyed", "FEED", 0.64,
     "Kinetic strike destroyed {FEED}; SITE01 and its dependants lose a power feed. "
     "Supported by R-005, R-006, R-007, R-016."),
    ("2", "H2 · Grid trip, supplier sabotage", "SUPX", 0.36,
     "{FEED} only tripped; the real effect is sabotage at {SUPX}, starving downstream sites of parts. "
     "Supported by R-010, R-011, R-014, R-015."),
)
