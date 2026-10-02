"""Turn the six exported source graphs into theatre nodes/edges: real joins, renames, derived
timestamps/coordinates, then hand off to links.py for the synthetic bridges."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config as cfg
from bridges import Placement, place_sites, place_suppliers, project_swarm
from countries import CountryMerge, merge_countries, pp_country_key
from enrich import centroid_coords, inherit_coords, ts_from_dmy, ts_from_step, ts_from_ymd
from extract import SourceGraph
from graph_model import GraphBuilder

Extras = dict[int, dict[str, object]]  # source node id -> additional properties


@dataclass
class Assembly:
    """Everything links.py needs to attach bridges onto the base graph."""

    builder: GraphBuilder
    sources: dict[str, SourceGraph]
    idmap: dict[tuple[str, int], int] = field(default_factory=dict)  # (source, source id) -> theatre id
    country_ids: dict[str, int] = field(default_factory=dict)  # MergedCountry.key -> theatre id
    sites: list[Placement] = field(default_factory=list)
    suppliers: list[Placement] = field(default_factory=list)

    def tid(self, source: str, source_id: int) -> int:
        return self.idmap[(source, int(source_id))]

    def ids_by_prop(self, source: str, label: str, prop: str) -> dict[str, int]:
        frame = self.sources[source].nodes[label].frame
        return {str(v): self.tid(source, i) for i, v in zip(frame["_id"], frame[prop])}


def _geo(lat: float, lon: float, method: str, synthetic: bool) -> dict[str, object]:
    props: dict[str, object] = {"latitude": lat, "longitude": lon, "geo_method": method}
    if synthetic:
        props["geo_synthetic"] = True
    return props


# ---------------------------------------------------------------- countries (real join)

def add_countries(asm: Assembly) -> CountryMerge:
    pp = asm.sources["power_plants"].nodes["Country"].frame
    lr = asm.sources["logistics_risk"].nodes["Country"].frame
    merge = merge_countries(list(zip(pp["country_code"], pp["name"])), lr["name"].tolist())

    plants = asm.sources["power_plants"].nodes["PowerPlant"].frame
    centre = plants.groupby("country_code")[["latitude", "longitude"]].median()
    for mc in merge.countries:
        props: dict[str, object] = {"name": mc.name, "country_code": mc.country_code,
                                    "source": "|".join(mc.sources), "logistics_name": mc.logistics_name}
        if mc.country_code in centre.index:
            row = centre.loc[mc.country_code]
            props |= _geo(round(float(row.latitude), 6), round(float(row.longitude), 6),
                          "median_of_power_plants", synthetic=False)
        asm.country_ids[mc.key] = asm.builder.add_node(("Country",), props, key=("Country", mc.key))

    for sid, code in zip(pp["_id"], pp["country_code"]):
        asm.idmap[("power_plants", int(sid))] = asm.country_ids[pp_country_key(code)]
    for sid, name in zip(lr["_id"], lr["name"]):
        asm.idmap[("logistics_risk", int(sid))] = asm.country_ids[merge.lr_name_to_key[name]]

    both = sum(1 for mc in merge.countries if len(mc.sources) == 2)
    print(f"[join] Country: {len(pp)} power_plants + {len(lr)} logistics_risk -> {len(merge.countries)} nodes "
          f"({both} merged); unmatched logistics_risk names: {list(merge.unmatched_lr) or 'none'}")
    return merge


# ---------------------------------------------------------------- per-label enrichment

def _rows_extra(frame: pd.DataFrame, fn) -> Extras:
    return {int(r["_id"]): fn(r) for r in frame.to_dict("records")}


def _coords_extra(coords: dict[int, tuple[float, float]], method: str) -> Extras:
    return {i: _geo(lat, lon, method, synthetic=False) for i, (lat, lon) in coords.items()}


def _placement_extra(frame: pd.DataFrame, key: str, placements: list[Placement]) -> Extras:
    by_key = {p.key: p for p in placements}
    out: Extras = {}
    for sid, k in zip(frame["_id"], frame[key]):
        p = by_key[k]
        out[int(sid)] = {"place": p.place, "country_code": p.country_code,
                         **_geo(p.latitude, p.longitude, "synthetic_placement", synthetic=True)}
    return out


def compute_extras(asm: Assembly) -> dict[tuple[str, str], Extras]:
    sc, pole, drone = (asm.sources[s] for s in ("supply_chain", "poledb", "drone_swarm"))
    extras: dict[tuple[str, str], Extras] = {}

    extras[("supply_chain", "Site")] = _placement_extra(sc.nodes["Site"].frame, "site_id", asm.sites)
    extras[("supply_chain", "Supplier")] = _placement_extra(sc.nodes["Supplier"].frame, "supplier_id",
                                                            asm.suppliers)
    extras[("supply_chain", "PurchaseOrder")] = _rows_extra(sc.nodes["PurchaseOrder"].frame,
                                                            lambda r: ts_from_ymd(r["order_date"]))
    extras[("supply_chain", "QualityIncident")] = _rows_extra(sc.nodes["QualityIncident"].frame,
                                                              lambda r: ts_from_ymd(r["incident_date"]))

    loc = pole.nodes["Location"].frame
    loc_coords = {int(i): (float(a), float(b)) for i, a, b in zip(loc["_id"], loc["latitude"], loc["longitude"])}
    crime_geo = _coords_extra(inherit_coords(pole.edges["OCCURRED_AT"].frame, loc_coords), "from_location")
    extras[("poledb", "Crime")] = _rows_extra(pole.nodes["Crime"].frame,
                                              lambda r: ts_from_dmy(r["date"]) | crime_geo.get(int(r["_id"]), {}))
    extras[("poledb", "PhoneCall")] = _rows_extra(pole.nodes["PhoneCall"].frame,
                                                  lambda r: ts_from_dmy(r["call_date"], r["call_time"]))
    extras[("poledb", "Person")] = _coords_extra(inherit_coords(pole.edges["CURRENT_ADDRESS"].frame, loc_coords),
                                                 "from_location")
    extras[("poledb", "PostCode")] = _coords_extra(
        centroid_coords(pole.edges["HAS_POSTCODE"].frame, loc_coords, "_src", "_dst"), "mean_of_locations")
    extras[("poledb", "Area")] = _coords_extra(
        centroid_coords(pole.edges["LOCATION_IN_AREA"].frame, loc_coords, "_src", "_dst"), "mean_of_locations")

    extras |= _drone_extras(asm, drone)
    return extras


def _drone_extras(asm: Assembly, drone: SourceGraph) -> dict[tuple[str, str], Extras]:
    centre = next(p for p in asm.sites if p.key == cfg.PATROL_SITE)
    rd = drone.nodes["Reading"].frame
    lat, lon = project_swarm(rd["x"].to_numpy(), rd["y"].to_numpy(), centre,
                             cfg.DRONE_METRES_PER_UNIT, cfg.DRONE_ORIGIN_XY)
    readings: Extras = {}
    for sid, step, la, lo in zip(rd["_id"], rd["timestamp"], lat, lon):
        readings[int(sid)] = (ts_from_step(int(step), cfg.DRONE_START, cfg.DRONE_STEP_SECONDS)
                              | _geo(float(la), float(lo), "synthetic_projection", synthetic=True))

    # Drone node position = its latest reading.
    of_drone = drone.edges["OF_DRONE"].frame.merge(rd[["_id", "timestamp"]], left_on="_src", right_on="_id")
    last = of_drone.sort_values(["_dst", "timestamp"]).groupby("_dst").tail(1)
    drones: Extras = {}
    for drone_id, reading_id in zip(last["_dst"], last["_src"]):
        r = readings[int(reading_id)]
        drones[int(drone_id)] = _geo(r["latitude"], r["longitude"], "last_reading", synthetic=True)
    return {("drone_swarm", "Reading"): readings, ("drone_swarm", "Drone"): drones}


# ---------------------------------------------------------------- original nodes and edges

def _base_props(source: str, label: str, row: dict[str, object]) -> dict[str, object]:
    props: dict[str, object] = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        name = cfg.PROPERTY_RENAMES.get((source, label, k), k)
        if name in cfg.FLOAT_PROPERTIES and v is not None and not pd.isna(v):
            v = float(v)
        props[name] = v
    key = cfg.PREFIXED_KEYS.get((source, label))
    if key:
        props["local_id"] = props[key]
        props[key] = f"{source}:{props[key]}"
    props["source"] = source
    return props


def add_source_nodes(asm: Assembly, extras: dict[tuple[str, str], Extras]) -> None:
    for source, graph in asm.sources.items():
        for label, table in graph.nodes.items():
            if label == "Country" and source in ("power_plants", "logistics_risk"):
                continue  # merged in add_countries
            extra = extras.get((source, label), {})
            for row in table.frame.to_dict("records"):
                sid = int(row["_id"])
                props = _base_props(source, label, row) | extra.get(sid, {})
                asm.idmap[(source, sid)] = asm.builder.add_node((label,), props)


def add_source_edges(asm: Assembly) -> None:
    for source, graph in asm.sources.items():
        for etype, table in graph.edges.items():
            props_cols = table.props
            for row in table.frame.to_dict("records"):
                props = {p: row[p] for p in props_cols} | {"source": source}
                asm.builder.add_edge(asm.tid(source, row["_src"]), asm.tid(source, row["_dst"]), etype, props)


def assemble_base(sources: dict[str, SourceGraph], rng: np.random.Generator) -> Assembly:
    asm = Assembly(GraphBuilder(), sources)
    site_ids = set(sources["supply_chain"].nodes["Site"].frame["site_id"])
    if site_ids != set(cfg.SITES):
        raise RuntimeError(f"config.SITES {sorted(cfg.SITES)} does not match supply_chain Sites {sorted(site_ids)}")
    asm.sites = place_sites(cfg.SITES, rng, cfg.SITE_JITTER_KM)
    sup_ids = sources["supply_chain"].nodes["Supplier"].frame["supplier_id"].tolist()
    asm.suppliers = place_suppliers(sup_ids, cfg.SUPPLIER_TOWNS, rng, cfg.SUPPLIER_JITTER_KM)

    add_countries(asm)
    add_source_nodes(asm, compute_extras(asm))
    add_source_edges(asm)

    expected_nodes = sum(s.node_total() for s in sources.values()) \
        - sum(len(sources[s].nodes["Country"].frame) for s in ("power_plants", "logistics_risk")) \
        + len(asm.country_ids)
    expected_edges = sum(s.edge_total() for s in sources.values())
    if len(asm.builder.nodes) != expected_nodes or len(asm.builder.edges) != expected_edges:
        raise RuntimeError(f"base graph has {len(asm.builder.nodes)}/{len(asm.builder.edges)} nodes/edges, "
                           f"expected {expected_nodes}/{expected_edges}")
    print(f"[base] {len(asm.builder.nodes):,} nodes, {len(asm.builder.edges):,} edges "
          f"(all original nodes/edges kept, Country merged)")
    return asm
