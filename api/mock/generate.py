"""Generate the mock fixture from the real `power_plants` graph plus the synthetic scenario.

    uv run python -m api.mock.generate          # needs a TuringDB server with power_plants on disk

Writes api/mock/fixtures/theatre_mock.json.gz. Plants and their NEAR edges are real; everything else
(sites, suppliers, parts, drones, crimes, reports, hypotheses) is seeded synthetic data.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
from turingdb import TuringDB

from api.config import load_settings
from api.mock import scenario as sc
from api.nodes import clean

FIXTURE_NAME = "theatre_mock.json.gz"
EARTH_KM = 6371.0088
PLANT_PROPS = ("name", "gppd_idnr", "capacity_mw", "latitude", "longitude", "primary_fuel", "commissioning_year",
               "owner", "country_code", "generation_gwh_2019", "source")

Edge = list[Any]  # [src, dst, rel, props]


def iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def haversine_km(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    p1, p2 = math.radians(lat), np.radians(lats)
    dphi, dlmb = p2 - p1, np.radians(lons) - math.radians(lon)
    a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def offset(lat: float, lon: float, east_km: float, north_km: float) -> tuple[float, float]:
    dlat = north_km / 110.574
    dlon = east_km / (111.320 * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def node(node_id: str, label: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"id": node_id, "label": label, "props": {k: v for k, v in props.items() if v is not None}}


# ------------------------------------------------------------------ real data

def fetch_plants(client: TuringDB) -> tuple[list[dict[str, Any]], list[Edge]]:
    client.load_graph("power_plants", raise_if_loaded=False)
    client.set_graph("power_plants")
    client.checkout()
    cols = ", ".join(f"n.{p}" for p in PLANT_PROPS)
    frame = client.query(f"MATCH (n:PowerPlant) RETURN n, {cols}")
    plants = []
    for row in frame.itertuples(index=False):
        props = {p: clean(v) for p, v in zip(PLANT_PROPS, row[1:])}
        props["data_source"], props["source"] = props.pop("source"), "power_plants"
        plants.append(node(str(row[0]), "PowerPlant", props))
    near = client.query("MATCH (p:PowerPlant)-[e:NEAR]->(q:PowerPlant) RETURN p, q, e.distance_km")
    edges = [[str(p), str(q), "NEAR", {"distance_km": float(d)}] for p, q, d in near.itertuples(index=False)]
    print(f"[mock] {len(plants):,} real plants, {len(edges):,} real NEAR edges from power_plants")
    return plants, edges


# ------------------------------------------------------------------ synthetic layers

def build_facilities(rng: np.random.Generator) -> list[dict[str, Any]]:
    sites = [node(f"site:{sid}", "Site", {"name": f"Site: {sid}", "site_id": sid, "place": place, "country_code": cc,
                                          "latitude": lat, "longitude": lon, "source": "supply_chain",
                                          "geo_synthetic": True})
             for sid, place, cc, lat, lon in sc.SITES]
    order = rng.permutation(len(sc.SUPPLIER_TOWNS))
    sups = []
    for i, town_idx in enumerate(order, start=1):
        place, cc, lat, lon = sc.SUPPLIER_TOWNS[town_idx]
        jlat, jlon = offset(lat, lon, rng.uniform(-4, 4), rng.uniform(-4, 4))
        sid = f"SUP{i:03d}"
        sups.append(node(f"sup:{sid}", "Supplier", {"name": f"Supplier: {sid}", "supplier_id": sid, "place": place,
                                                    "country_code": cc, "latitude": jlat, "longitude": jlon,
                                                    "source": "supply_chain", "geo_synthetic": True}))
    for n in sites + sups:
        runs = sc.RUNS_BY_LABEL[n["label"]]
        n["props"]["exposure"] = sum(sc.ATTACKS_BY_ASSET_TYPE[t] for t in runs)
        n["props"]["runs"] = ", ".join(runs)
    return sites + sups


def build_powered_by(facilities: list[dict[str, Any]], plants: list[dict[str, Any]]) -> list[Edge]:
    lats = np.array([p["props"]["latitude"] for p in plants])
    lons = np.array([p["props"]["longitude"] for p in plants])
    edges = []
    for f in facilities:
        d = haversine_km(f["props"]["latitude"], f["props"]["longitude"], lats, lons)
        for idx in np.argsort(d)[: sc.POWERED_BY_K]:
            if d[idx] <= sc.POWERED_BY_MAX_KM:
                edges.append([f["id"], plants[idx]["id"], "POWERED_BY",
                              {"distance_km": round(float(d[idx]), 3), "synthetic": True}])
    return edges


def build_parts(rng: np.random.Generator, facilities: list[dict[str, Any]]) -> tuple[list, list[Edge]]:
    sups = [f for f in facilities if f["label"] == "Supplier"]
    sites = [f for f in facilities if f["label"] == "Site"]
    weights = rng.dirichlet(np.full(len(sups), 0.6))
    parts, edges = [], []
    for i in range(1, sc.PART_COUNT + 1):
        pid = f"P{i:05d}"
        family = sc.PART_FAMILIES[int(rng.integers(len(sc.PART_FAMILIES)))]
        crit = str(rng.choice(["A", "B", "C"], p=[0.25, 0.45, 0.30]))
        parts.append(node(f"part:{pid}", "Part", {"name": f"Part: {pid}", "part_id": pid, "part_family": family,
                                                  "criticality_class": crit, "source": "supply_chain",
                                                  "lead_time_days": float(rng.integers(20, 180))}))
        sup = sups[int(rng.choice(len(sups), p=weights))]
        edges.append([f"part:{pid}", sup["id"], "SUPPLIED_BY", {"synthetic": True}])
        for s in rng.choice(len(sites), size=int(rng.integers(1, 4)), replace=False):
            edges.append([f"part:{pid}", sites[int(s)]["id"], "DELIVERED_TO", {"synthetic": True}])
    return parts, edges


def drone_position(i: int, step: int, params: tuple[float, float, float, float],
                   site: tuple[float, float]) -> tuple[float, float]:
    radius_km, period_steps, phase, wobble = params
    angle = phase + 2 * math.pi * step / period_steps
    r = radius_km * (1 + wobble * math.sin(3 * angle))
    if i % 4 == 3:  # figure-of-eight patrol
        return offset(site[0], site[1], r * math.sin(angle), r * math.sin(angle) * math.cos(angle))
    return offset(site[0], site[1], r * math.cos(angle), r * math.sin(angle))


def build_drones(rng: np.random.Generator) -> tuple[list, list[Edge], list[dict[str, Any]]]:
    site = next((lat, lon) for sid, _, _, lat, lon in sc.SITES if sid == sc.PATROL_SITE)
    nodes, edges, tracks = [], [], []
    for i in range(sc.DRONE_COUNT):
        params = (rng.uniform(0.6, 3.2), rng.uniform(120, 400), rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.25))
        steps = range(0, sc.DRONE_STEPS, sc.DRONE_TRACK_EVERY)
        path = [drone_position(i, s, params, site) for s in steps]
        stamps = [int((sc.TIMELINE_START + timedelta(seconds=s * sc.DRONE_STEP_SECONDS)).timestamp()) for s in steps]
        last_lat, last_lon = path[-1]
        did = f"drone:{i}"
        nodes.append(node(did, "Drone", {"name": f"Drone: {i}", "drone_id": str(i), "latitude": last_lat,
                                         "longitude": last_lon, "source": "drone_swarm", "geo_synthetic": True,
                                         "mission": "ISR"}))
        edges.append([did, f"site:{sc.PATROL_SITE}", "PATROLS", {"mission": "ISR", "synthetic": True}])
        tracks.append({"id": did, "name": f"Drone: {i}", "path": [[lon, lat] for lat, lon in path],
                       "timestamps": stamps})
    return nodes, edges, tracks


def build_crimes(rng: np.random.Generator) -> tuple[list, list[Edge]]:
    centres = {sid: (lat, lon) for sid, _, _, lat, lon in sc.SITES}
    nodes, edges, n = [], [], 0
    for sid, count in sc.CRIME_COUNTS.items():
        lat0, lon0 = centres[sid]
        for _ in range(count):
            n += 1
            dist = sc.CRIME_RADIUS_KM * math.sqrt(rng.uniform(0.02, 1))
            ang = rng.uniform(0, 2 * math.pi)
            lat, lon = offset(lat0, lon0, dist * math.cos(ang), dist * math.sin(ang))
            ctype = sc.CRIME_TYPES[int(rng.integers(len(sc.CRIME_TYPES)))]
            day = int(rng.integers(1, 31))
            cid = f"crime:{n}"
            nodes.append(node(cid, "Crime", {"name": f"Crime: {ctype}", "type": ctype, "latitude": lat,
                                             "longitude": lon, "timestamp": f"2017-08-{day:02d}T00:00:00Z",
                                             "source": "poledb"}))
            edges.append([cid, f"site:{sid}", "NEAR", {"distance_km": round(dist, 3), "synthetic": True}])
    return nodes, edges


# ------------------------------------------------------------------ scenario subjects, reports, history

def pick_subjects(nodes_by_id: dict[str, dict], edges: list[Edge]) -> dict[str, str]:
    feeds = [e[1] for e in edges if e[2] == "POWERED_BY" and e[0] == f"site:{sc.PATROL_SITE}"]
    feed = max(feeds, key=lambda pid: nodes_by_id[pid]["props"].get("capacity_mw") or 0)
    part_sup = {e[0]: e[1] for e in edges if e[2] == "SUPPLIED_BY"}
    reach: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e[2] == "DELIVERED_TO":
            reach[part_sup[e[0]]].add(e[1])
    supx = max(sorted(reach), key=lambda s: (len(reach[s]), sum(1 for p in part_sup.values() if p == s)))
    return {"FEED": feed, "SUPX": supx, "SITE01": "site:SITE01", "SITE02": "site:SITE02"}


def build_reports(subjects: dict[str, str], nodes_by_id: dict[str, dict], rng: np.random.Generator):
    names = {"FEED": nodes_by_id[subjects["FEED"]]["props"]["name"],
             "SUPX": nodes_by_id[subjects["SUPX"]]["props"]["name"].replace("Supplier: ", ""),
             "SUPX_PLACE": nodes_by_id[subjects["SUPX"]]["props"]["place"]}
    nodes, edges = [], []
    for rid, batch, hhmm, stype, conf, claim, subject, text, contradicts in sc.REPORT_SCRIPT:
        target = nodes_by_id[subjects[subject]]["props"]
        lat, lon = offset(target["latitude"], target["longitude"], rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6))
        hh, mm = (int(x) for x in hhmm.split(":"))
        when = sc.TIMELINE_START.replace(hour=hh, minute=mm)
        nid = f"report:{rid}"
        nodes.append(node(nid, "Report", {
            "name": f"Report: {rid}", "report_id": rid, "batch": batch, "timestamp": iso(when),
            "ts_epoch": int(when.timestamp()), "source_type": stype, "confidence": conf, "claim": claim,
            "text": text.format(**names), "latitude": lat, "longitude": lon, "source": "intel",
            "synthetic": True}))
        edges.append([nid, subjects[subject], "MENTIONS", {"synthetic": True}])
        if contradicts:
            edges.append([nid, f"report:{contradicts}", "CONTRADICTS", {"synthetic": True}])
    return nodes, edges


def build_commits(base_nodes: int, base_edges: int, reports: list[dict], report_edges: list[Edge]) -> list[dict]:
    batch_of = {r["id"]: r["props"]["batch"] for r in reports}
    nodes_per_batch = Counter(batch_of.values())
    edges_per_batch = Counter(batch_of[e[0]] for e in report_edges)
    commits = [{"node_delta": base_nodes, "edge_delta": base_edges}]
    commits += [{"node_delta": nodes_per_batch[b], "edge_delta": edges_per_batch[b]} for b in sorted(nodes_per_batch)]
    return [{"hash": hashlib.sha1(f"opsmap-mock-{i}".encode()).hexdigest()[:16], "index": i, **c}
            for i, c in enumerate(commits)]


def build_fixture(client: TuringDB) -> dict[str, Any]:
    rng = np.random.default_rng(sc.SEED)
    plants, near = fetch_plants(client)
    facilities = build_facilities(rng)
    parts, part_edges = build_parts(rng, facilities)
    drones, drone_edges, tracks = build_drones(rng)
    crimes, crime_edges = build_crimes(rng)
    base_nodes = plants + facilities + parts + drones + crimes
    base_edges = near + build_powered_by(facilities, plants) + part_edges + drone_edges + crime_edges
    by_id = {n["id"]: n for n in base_nodes}
    subjects = pick_subjects(by_id, base_edges)
    reports, report_edges = build_reports(subjects, by_id, rng)
    names = {"FEED": by_id[subjects["FEED"]]["props"]["name"],
             "SUPX": by_id[subjects["SUPX"]]["props"]["name"].replace("Supplier: ", "")}
    hypotheses = [{"id": hid, "label": label, "confidence": conf, "strike": [subjects[subject]],
                   "description": desc.format(**names)}
                  for hid, label, subject, conf, desc in sc.HYPOTHESES]
    print(f"[mock] FEED = {names['FEED']} ({subjects['FEED']}), SUPX = {names['SUPX']} ({subjects['SUPX']})")
    return {
        "meta": {"description": "OpsMap mock theatre: real power_plants + synthetic scenario", "seed": sc.SEED},
        "nodes": base_nodes + reports,
        "edges": base_edges + report_edges,
        "commits": build_commits(len(base_nodes), len(base_edges), reports, report_edges),
        "hypotheses": hypotheses,
        "tracks": tracks,
    }


def main() -> None:
    settings = load_settings()
    fixture = build_fixture(TuringDB(host=settings.turingdb_host))
    out: Path = settings.fixtures_dir / FIXTURE_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(fixture, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"[mock] wrote {out} ({out.stat().st_size / 1e6:.1f} MB): {len(fixture['nodes']):,} nodes, "
          f"{len(fixture['edges']):,} edges, {len(fixture['commits'])} commits, {len(fixture['hypotheses'])} hypotheses")


if __name__ == "__main__":
    main()
