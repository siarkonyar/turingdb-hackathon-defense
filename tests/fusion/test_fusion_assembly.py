"""In-memory end-to-end test of the fusion logic on tiny fake source graphs (no server needed)."""

import numpy as np
import pandas as pd
import pytest

from assemble import assemble_base
from extract import SourceGraph, Table
from config import SITES, SUPPLIER_TOWNS
from links import add_synthetic_links

OTHER_ISO3 = sorted(({t[1] for t in SUPPLIER_TOWNS} | {s[1] for s in SITES.values()}) - {"GBR", "FRA"})


def _t(name: str, rows: list[dict]) -> Table:
    return Table(name, pd.DataFrame(rows), {})


def _sources() -> dict[str, SourceGraph]:
    # Three plants around Trafford Park (SITE01), one far away in France.
    plants = [dict(_id=i, gppd_idnr=f"GBR{i}", name=f"P{i}", latitude=53.47 + d, longitude=-2.31,
                   country_code="GBR", source="WRI", primary_fuel="Gas") for i, d in enumerate((0.01, 0.02, 0.03))]
    plants.append(dict(_id=3, gppd_idnr="FRA0", name="Far", latitude=43.6, longitude=1.4, country_code="FRA",
                       source="WRI", primary_fuel="Hydro"))
    power = SourceGraph("power_plants", {
        "PowerPlant": _t("PowerPlant", plants),
        "Country": _t("Country", [dict(_id=10, country_code="GBR", name="United Kingdom"),
                                  dict(_id=11, country_code="FRA", name="France")]
                      + [dict(_id=20 + i, country_code=c, name=c) for i, c in enumerate(OTHER_ISO3)]),
    }, {
        "LOCATED_IN": _t("LOCATED_IN", [dict(_src=i, _dst=10 if i < 3 else 11) for i in range(4)]),
        "NEAR": _t("NEAR", [dict(_src=0, _dst=1, distance_km=1.1)]),
    })
    supply = SourceGraph("supply_chain", {
        "Site": _t("Site", [dict(_id=0, site_id="SITE01")] + [dict(_id=10 + i, site_id=f"SITE0{i}") for i in range(2, 7)]),
        "Supplier": _t("Supplier", [dict(_id=1, supplier_id="SUP001"), dict(_id=2, supplier_id="SUP002")]),
        "Part": _t("Part", [dict(_id=3, part_id="P1", lead_time_days=30, criticality_class="A")]),
        "PurchaseOrder": _t("PurchaseOrder", [dict(_id=4, po_id="PO1", order_date="2024-12-16")]),
        "QualityIncident": _t("QualityIncident", [dict(_id=5, incident_id="Q1", incident_date="2023-05-30")]),
    }, {
        "FROM_SUPPLIER": _t("FROM_SUPPLIER", [dict(_src=4, _dst=1)]),
        "DELIVERED_TO": _t("DELIVERED_TO", [dict(_src=4, _dst=0)]),
    })
    logistics = SourceGraph("logistics_risk", {
        "Supplier": _t("Supplier", [dict(_id=0, supplier_id="P0001_S1"), dict(_id=1, supplier_id="P0002_S1")]),
        "Country": _t("Country", [dict(_id=2, name="UK"), dict(_id=3, name="Haiti")]),
        "Shipment": _t("Shipment", [dict(_id=4, shipment_id="INST1", lead_time_days=2.5)]),
    }, {
        "LOCATED_IN": _t("LOCATED_IN", [dict(_src=0, _dst=2), dict(_src=1, _dst=3)]),
        "FROM_SUPPLIER": _t("FROM_SUPPLIER", [dict(_src=4, _dst=0)]),
    })
    drone = SourceGraph("drone_swarm", {
        "Reading": _t("Reading", [dict(_id=0, reading_id="D0_T0", timestamp=0, x=50.0, y=50.0),
                                  dict(_id=1, reading_id="D0_T1", timestamp=1, x=60.0, y=50.0)]),
        "Drone": _t("Drone", [dict(_id=2, drone_id="0")]),
    }, {"OF_DRONE": _t("OF_DRONE", [dict(_src=0, _dst=2), dict(_src=1, _dst=2)])})
    pole = SourceGraph("poledb", {
        "Location": _t("Location", [dict(_id=0, address="1 A St", latitude=53.475, longitude=-2.31),
                                    dict(_id=1, address="1 A St", latitude=53.9, longitude=-2.9)]),
        "Crime": _t("Crime", [dict(_id=2, id="c1", date="21/08/2017", type="Burglary")]),
        "PhoneCall": _t("PhoneCall", [dict(_id=3, call_date="10/08/2017", call_time="20:32")]),
        "Person": _t("Person", [dict(_id=4, nhs_no="111")]),
        "PostCode": _t("PostCode", [dict(_id=5, code="M5")]),
        "Area": _t("Area", [dict(_id=6, areaCode="M")]),
    }, {
        "OCCURRED_AT": _t("OCCURRED_AT", [dict(_src=2, _dst=0)]),
        "CURRENT_ADDRESS": _t("CURRENT_ADDRESS", [dict(_src=4, _dst=0)]),
        "HAS_POSTCODE": _t("HAS_POSTCODE", [dict(_src=0, _dst=5), dict(_src=1, _dst=5)]),
        "LOCATION_IN_AREA": _t("LOCATION_IN_AREA", [dict(_src=0, _dst=6)]),
    })
    attacks = SourceGraph("attack_scenarios", {
        "Attack": _t("Attack", [dict(_id=0, attack_id="A1", target_type="PLC", tags="modbus", source="kb"),
                                dict(_id=1, attack_id="A2", target_type="Robot", tags=None, source="kb")]),
    }, {})
    return {s.name: s for s in (power, supply, logistics, drone, pole, attacks)}


@pytest.fixture(scope="module")
def built():
    rng = np.random.default_rng(20261002)
    asm = assemble_base(_sources(), rng)
    add_synthetic_links(asm, rng)
    return asm


def _node(asm, source, sid):
    return asm.builder.nodes[asm.tid(source, sid)]


def _edges(asm, etype):
    return [e for e in asm.builder.edges if e.edge_type == etype]


def test_countries_merge_on_exact_keys(built):
    countries = [n for n in built.builder.nodes if n.labels == ("Country",)]
    assert len(countries) == 3 + len(OTHER_ISO3)  # GBR (merged), FRA, Haiti (logistics only), filler
    assert built.tid("logistics_risk", 2) == built.tid("power_plants", 10)  # UK == GBR
    haiti = _node(built, "logistics_risk", 3).props
    assert "country_code" not in haiti and haiti["source"] == "logistics_risk"
    assert _node(built, "power_plants", 10).props["source"] == "power_plants|logistics_risk"


def test_keys_prefixed_renamed_and_sourced(built):
    sc = _node(built, "supply_chain", 1).props
    lr = _node(built, "logistics_risk", 0).props
    assert sc["supplier_id"] == "supply_chain:SUP001" and sc["local_id"] == "SUP001"
    assert lr["supplier_id"] == "logistics_risk:P0001_S1"
    plant = _node(built, "power_plants", 0).props
    assert plant["data_source"] == "WRI" and plant["source"] == "power_plants"
    assert _node(built, "supply_chain", 3).props["lead_time_days"] == 30.0
    assert all("source" in n.props for n in built.builder.nodes)


def test_events_get_timestamps_and_coordinates(built):
    assert _node(built, "supply_chain", 4).props["timestamp"] == "2024-12-16T00:00:00Z"
    crime = _node(built, "poledb", 2).props
    assert crime["timestamp"] == "2017-08-21T00:00:00Z" and crime["latitude"] == 53.475
    assert _node(built, "poledb", 3).props["timestamp"] == "2017-08-10T20:32:00Z"
    reading = _node(built, "drone_swarm", 0).props
    assert reading["timestep"] == 0 and reading["timestamp"] == "2026-09-29T05:00:00Z" and reading["geo_synthetic"]
    drone = _node(built, "drone_swarm", 2).props
    assert drone["latitude"] == _node(built, "drone_swarm", 1).props["latitude"]  # last reading
    assert _node(built, "poledb", 5).props["latitude"] == pytest.approx((53.475 + 53.9) / 2)
    site = _node(built, "supply_chain", 0).props
    assert site["geo_synthetic"] and site["country_code"] == "GBR"


def test_original_edges_kept_and_repointed(built):
    located = _edges(built, "LOCATED_IN")
    gbr = built.tid("power_plants", 10)
    assert sum(1 for e in located if e.end == gbr and e.props["source"] == "logistics_risk") == 1
    assert _edges(built, "NEAR")[0].props == {"distance_km": 1.1, "source": "power_plants"}


def test_synthetic_bridges(built):
    site = built.tid("supply_chain", 0)
    powered = [e for e in _edges(built, "POWERED_BY") if e.start == site]
    assert len(powered) == 3 and all(e.props["synthetic"] for e in powered)
    assert all(e.props["distance_km"] <= 50 for e in _edges(built, "POWERED_BY"))
    patrol = _edges(built, "PATROLS")
    assert [(e.start, e.end) for e in patrol] == [(built.tid("drone_swarm", 2), site)]
    near_site = [e for e in _edges(built, "NEAR") if e.end == site]
    assert [e.start for e in near_site] == [built.tid("poledb", 0)] and near_site[0].props["synthetic"]
    targets = _edges(built, "TARGETS")
    assert {e.props["keyword"] for e in targets} == {"plc"} and len(targets) == 1
    runs = _edges(built, "RUNS")
    assert len(runs) == 4 * 2 + 6 * 5 + 2 * 3 + 2 * 2 + 1 * 2  # plants, sites, part suppliers, logistics, drone


def test_sources_from_only_links_same_country(built):
    uk_logistics = built.tid("logistics_risk", 0)
    for e in _edges(built, "SOURCES_FROM"):
        assert built.builder.nodes[e.start].props["country_code"] == "GBR"  # only GBR has a logistics pool
        assert e.end == uk_logistics


def test_site_config_must_match_data():
    sources = _sources()
    frame = sources["supply_chain"].nodes["Site"].frame
    sources["supply_chain"].nodes["Site"] = _t("Site", frame.iloc[:1].to_dict("records"))
    with pytest.raises(RuntimeError, match="config.SITES"):
        assemble_base(sources, np.random.default_rng(0))
