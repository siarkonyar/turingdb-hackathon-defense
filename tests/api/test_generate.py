"""The mock generator's pure functions (no TuringDB needed): geometry, synthetic layers, history."""

from __future__ import annotations

import numpy as np
import pytest

from api.mock import generate as g
from api.mock import scenario as sc


def plant(pid: str, lat: float, lon: float, mw: float) -> dict:
    return g.node(pid, "PowerPlant", {"name": pid, "latitude": lat, "longitude": lon, "capacity_mw": mw})


def test_haversine_and_offset_are_consistent():
    lat, lon = g.offset(53.0, -2.0, east_km=3.0, north_km=4.0)
    assert g.haversine_km(53.0, -2.0, np.array([lat]), np.array([lon]))[0] == pytest.approx(5.0, rel=0.01)


def test_facilities_get_exposure_from_the_systems_they_run():
    facilities = g.build_facilities(np.random.default_rng(1))
    sites = [f for f in facilities if f["label"] == "Site"]
    sups = [f for f in facilities if f["label"] == "Supplier"]
    assert len(sites) == len(sc.SITES) and len(sups) == len(sc.SUPPLIER_TOWNS)
    expected = sum(sc.ATTACKS_BY_ASSET_TYPE[t] for t in sc.RUNS_BY_LABEL["Site"])
    assert {s["props"]["exposure"] for s in sites} == {expected}


def test_powered_by_takes_nearest_plants_within_range():
    site = g.node("site:A", "Site", {"latitude": 53.0, "longitude": -2.0})
    plants = [plant("near", 53.01, -2.0, 10), plant("mid", 53.1, -2.0, 10), plant("far", 60.0, 10.0, 10)]
    edges = g.build_powered_by([site], plants)
    assert [e[1] for e in edges] == ["near", "mid"]  # "far" is beyond POWERED_BY_MAX_KM
    assert all(e[2] == "POWERED_BY" and e[3]["distance_km"] > 0 for e in edges)


def test_parts_drones_and_crimes_are_wired_to_the_scenario():
    rng = np.random.default_rng(sc.SEED)
    facilities = g.build_facilities(rng)
    parts, part_edges = g.build_parts(rng, facilities)
    assert len(parts) == sc.PART_COUNT
    assert sum(e[2] == "SUPPLIED_BY" for e in part_edges) == sc.PART_COUNT
    drones, drone_edges, tracks = g.build_drones(rng)
    assert len(drones) == len(tracks) == sc.DRONE_COUNT
    assert all(len(t["path"]) == len(t["timestamps"]) for t in tracks)
    assert {e[1] for e in drone_edges} == {f"site:{sc.PATROL_SITE}"}
    crimes, crime_edges = g.build_crimes(rng)
    assert len(crimes) == sum(sc.CRIME_COUNTS.values())
    assert max(e[3]["distance_km"] for e in crime_edges) <= sc.CRIME_RADIUS_KM


def test_subjects_reports_and_commits():
    rng = np.random.default_rng(sc.SEED)
    facilities = g.build_facilities(rng)
    site01 = next(f for f in facilities if f["id"] == "site:SITE01")["props"]
    plants = [plant("big", site01["latitude"] + 0.01, site01["longitude"], 900),
              plant("small", site01["latitude"] - 0.01, site01["longitude"], 5)]
    parts, part_edges = g.build_parts(rng, facilities)
    edges = g.build_powered_by(facilities, plants) + part_edges
    by_id = {n["id"]: n for n in facilities + parts + plants}
    subjects = g.pick_subjects(by_id, edges)
    assert subjects["FEED"] == "big"
    reports, report_edges = g.build_reports(subjects, by_id, rng)
    assert len(reports) == len(sc.REPORT_SCRIPT)
    assert all("{" not in r["props"]["text"] for r in reports)  # placeholders resolved
    commits = g.build_commits(10, 20, reports, report_edges)
    assert commits[0]["node_delta"] == 10 and len(commits) == 1 + len({r["props"]["batch"] for r in reports})
    assert sum(c["node_delta"] for c in commits[1:]) == len(reports)
