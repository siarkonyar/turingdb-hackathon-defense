"""Hand-written synthetic intelligence reports for the theatre operating picture.

Every report is fictional (synthetic: true). Asset keys reference real nodes in the fused
graph; build_theatre.py fails if a key matches zero or several nodes. Contradicting pairs
(later report -[:CONTRADICTS]-> earlier report) seed competing hypothesis branches:

    RPT-08 vs RPT-01  Wedel power station struck / operating normally
    RPT-09 vs RPT-02  SITE01 west fence breached / fence intact
    RPT-10 vs RPT-03  insider lead on a 54 Barton Street resident / resident was abroad
    RPT-13 vs RPT-05  Barcelona port strike halts SUP012 / port operating normally
    RPT-14 vs RPT-07  Lockleaze storage intact / battery fire at Lockleaze
    RPT-18 vs RPT-17  EC Rzeszow unplanned shutdown / scheduled test, plant online
"""

from reports import Mention, Report


def plant(gppd_idnr: str) -> Mention:
    return Mention("PowerPlant", "gppd_idnr", gppd_idnr)


def site(site_id: str) -> Mention:
    return Mention("Site", "site_id", site_id)


def supplier(supplier_id: str) -> Mention:
    return Mention("Supplier", "supplier_id", supplier_id)


def person(nhs_no: str) -> Mention:
    return Mention("Person", "nhs_no", nhs_no)


def drone(drone_id: str) -> Mention:
    return Mention("Drone", "drone_id", drone_id)


def asset_type(asset_type_id: str) -> Mention:
    return Mention("AssetType", "asset_type_id", asset_type_id)


WEDEL_COAL, WEDEL_OIL = "WRI1006130", "WRI1006131"
EC_RZESZOW = "WRI1019087"
SALFORD_AD, NEWHAVEN_EFW = "GBR0000912", "GBR0000897"
LOCKLEAZE = "GBR2001167"
HUGHES, GORDON, THOMPSON, AUSTIN = "821-11-2735", "585-92-9741", "552-54-9978", "641-55-5639"

BATCH_1 = (
    Report("RPT-01", 1, "2026-09-28T21:40:00Z", "OSINT", 0.55, 53.5670, 9.7244, "struck",
           "Multiple social media videos geolocated to Wedel show a large explosion and fire at the Wedel "
           "power station on the Elbe. Plume visible from Hamburg-Finkenwerder. Cause unknown; possible "
           "one-way attack drone. Wedel is one of three plants feeding SITE04.",
           (plant(WEDEL_COAL), site("SITE04"))),
    Report("RPT-02", 1, "2026-09-29T05:12:00Z", "drone", 0.70, 53.4735, -2.3170, "breach",
           "ISR swarm patrol over SITE01 (Trafford Park): thermal imagery from drones 3 and 7 shows a gap in "
           "the west perimeter fence and two vehicles parked without lights 40 m from the gap at 05:12Z.",
           (site("SITE01"), drone("3"), drone("7"))),
    Report("RPT-03", 1, "2026-09-29T09:30:00Z", "HUMINT", 0.50, 53.4759, -2.2523, "insider_lead",
           "Walk-in source claims a cleaning contractor with badge access to SITE01 lives at 54 Barton Street "
           "and has been asking colleagues about shift changes at the substation. Source named the resident "
           "as Stephanie Hughes. Source reliability unproven.",
           (person(HUGHES), site("SITE01"), asset_type("PHYSICAL_ACCESS"))),
    Report("RPT-04", 1, "2026-09-28T23:05:00Z", "SIGINT", 0.65, 50.0646, 22.0294, "threat_reporting",
           "Intercepted messaging on a channel linked to a hostile service references the Rzeszow plant and "
           "timing before the convoy. Assessed as interest in EC Rzeszow, the gas CHP 5 km from the "
           "SITE06 logistics hub at Jasionka.",
           (plant(EC_RZESZOW), site("SITE06"))),
    Report("RPT-05", 1, "2026-09-29T07:00:00Z", "OSINT", 0.60, 41.3550, 2.1413, "disrupted",
           "Dockworker unions at the Port of Barcelona announce an immediate 72-hour strike. Outbound "
           "containers for supplier SUP012 (Barcelona, five class A parts) and its port-side logistics "
           "provider are held at the terminal.",
           (supplier("supply_chain:SUP012"), supplier("logistics_risk:P0189_S2"))),
    Report("RPT-06", 1, "2026-09-29T02:15:00Z", "SIGINT", 0.75, 53.4953, -2.2873, "cyber_intrusion",
           "Anomalous Modbus write commands from a foreign VPS to an internet-exposed HMI at Salford Refuse "
           "Treatment Plant, one of three plants powering SITE01. Pattern matches known ICS reconnaissance "
           "tooling.",
           (plant(SALFORD_AD), site("SITE01"), asset_type("ICS_SCADA"))),
    Report("RPT-07", 1, "2026-09-29T10:20:00Z", "OSINT", 0.60, 51.4849, -2.5716, "operational",
           "Commercial satellite pass at 10:05Z shows Lockleaze Energy Storage in Bristol intact, with no "
           "thermal signature. The site backs up supplier SUP032 (Bristol) in the event of grid loss.",
           (plant(LOCKLEAZE), supplier("supply_chain:SUP032"))),
)

BATCH_2 = (
    Report("RPT-08", 2, "2026-09-29T14:00:00Z", "SIGINT", 0.80, 53.5670, 9.7244, "operational",
           "Grid telemetry intercepts show Wedel coal units synchronised and exporting about 230 MW since "
           "midnight. No forced outage registered with the TSO. The fire on video is likely the adjacent "
           "oil unit or a hoax.",
           (plant(WEDEL_COAL), plant(WEDEL_OIL)), contradicts="RPT-01"),
    Report("RPT-09", 2, "2026-09-29T15:30:00Z", "drone", 0.65, 53.4733, -2.3168, "no_breach",
           "Re-tasked daylight overflight by drones 5 and 12 shows the SITE01 west fence intact. The gap seen "
           "on thermal is a gate left open by a maintenance crew; the vehicles belong to the crew.",
           (site("SITE01"), drone("5"), drone("12")), contradicts="RPT-02"),
    Report("RPT-10", 2, "2026-09-29T18:45:00Z", "HUMINT", 0.70, 53.4759, -2.2523, "cleared",
           "Established source with access to travel records states Stephanie Hughes has been in Malaga "
           "since 25 Sep and returns on 2 Oct. She cannot be the contractor described in RPT-03; her "
           "housemates at 54 Barton Street remain unverified.",
           (person(HUGHES),), contradicts="RPT-03"),
    Report("RPT-11", 2, "2026-09-29T23:10:00Z", "OSINT", 0.55, 53.4840, -2.2700, "outage",
           "Residents in Salford and Trafford Park report a 40-minute power cut from 22:20. The local DNO "
           "cites a fault on the circuit fed by Salford Refuse Treatment Plant and the Newhaven EFW plant.",
           (site("SITE01"), plant(SALFORD_AD), plant(NEWHAVEN_EFW))),
    Report("RPT-12", 2, "2026-09-30T08:00:00Z", "HUMINT", 0.60, 53.4953, -2.2873, "vulnerable",
           "Maintenance engineer at Salford Refuse Treatment Plant reports the HMI was replaced two weeks ago "
           "by a third-party integrator who left remote access enabled with default credentials.",
           (plant(SALFORD_AD), asset_type("ICS_SCADA"), asset_type("OT_NETWORK"))),
    Report("RPT-13", 2, "2026-09-30T11:30:00Z", "SIGINT", 0.70, 41.3550, 2.1413, "operational",
           "Port community system messages show container moves at the Barcelona terminal at normal rates "
           "since 06:00. The strike was suspended overnight; SUP012 consignments are loaded.",
           (supplier("supply_chain:SUP012"), supplier("logistics_risk:P0189_S2")), contradicts="RPT-05"),
    Report("RPT-14", 2, "2026-09-30T16:45:00Z", "OSINT", 0.50, 51.4849, -2.5716, "damaged",
           "Avon Fire and Rescue posts that crews are attending a battery fire at Lockleaze Energy Storage. "
           "Smoke visible across north Bristol; road closures around the site.",
           (plant(LOCKLEAZE), supplier("supply_chain:SUP032")), contradicts="RPT-07"),
    Report("RPT-17", 2, "2026-09-30T20:00:00Z", "SIGINT", 0.60, 50.0646, 22.0294, "offline",
           "Plant control traffic indicates an unplanned trip of the main gas turbine at EC Rzeszow after a "
           "control-system fault. SITE06 is running on backup generation.",
           (plant(EC_RZESZOW), site("SITE06"), asset_type("ICS_SCADA"))),
)

BATCH_3 = (
    Report("RPT-15", 3, "2026-10-01T02:40:00Z", "drone", 0.85, 53.4748, -2.3105, "hostile_surveillance",
           "Drones 0 and 11, thermal: two individuals photographing the SITE01 substation from the north "
           "fence line at 02:40Z, then leaving east on foot towards Salford Quays.",
           (site("SITE01"), drone("0"), drone("11"))),
    Report("RPT-16", 3, "2026-10-01T09:15:00Z", "HUMINT", 0.55, 53.4614, -2.2496, "insider_lead",
           "Source reports that the three residents of 106 Rook Street (Craig Gordon, Bobby Thompson, Brian "
           "Austin) were paid cash to take night photos of the Trafford Park site. One of them claims a "
           "friend works on the site cleaning contract.",
           (person(GORDON), person(THOMPSON), person(AUSTIN), site("SITE01"))),
    Report("RPT-18", 3, "2026-10-01T10:00:00Z", "OSINT", 0.70, 50.0646, 22.0294, "operational",
           "Grid operator statement: EC Rzeszow performed a scheduled protection test on 30 Sep and has been "
           "at full output since 23:00. No fault occurred.",
           (plant(EC_RZESZOW),), contradicts="RPT-17"),
    Report("RPT-19", 3, "2026-10-01T11:20:00Z", "OSINT", 0.65, 53.5663, 9.7285, "partially_damaged",
           "New satellite imagery of Wedel: no visible damage to the coal units; scorch marks and a collapsed "
           "tank roof at the adjacent oil-fired unit.",
           (plant(WEDEL_COAL), plant(WEDEL_OIL))),
    Report("RPT-20", 3, "2026-10-01T13:00:00Z", "SIGINT", 0.80, 53.5265, 9.8260, "cyber_targeting",
           "Spear-phishing campaign against Hamburg utility and aerospace staff, lures themed on the Wedel "
           "incident. Payload harvests VPN credentials; recipients include SITE04 engineering.",
           (plant(WEDEL_COAL), site("SITE04"), asset_type("CORPORATE_IT"))),
    Report("RPT-21", 3, "2026-10-01T15:30:00Z", "HUMINT", 0.60, 50.6114, 5.5786, "delayed",
           "Carrier contact reports trucks from SUP040 (Liege), the largest supplier to SITE04, rerouted "
           "away from the A1 corridor after the Wedel incident. Expect 48-72 h delays on open POs.",
           (supplier("supply_chain:SUP040"), site("SITE04"))),
)

REPORTS: tuple[Report, ...] = BATCH_1 + BATCH_2 + BATCH_3
