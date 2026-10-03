"""Synthetic bridge edges and AssetType nodes attached onto the assembled base graph."""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

import config as cfg
from assemble import Assembly
from assets import ASSET_TYPES, RUNS_BY_KIND, match_asset_types
from bridges import near_links, powered_by, sources_from
from geo import nearest_within

SYNTHETIC = {"synthetic": True, "source": "theatre"}
DERIVED = {"synthetic": False, "source": "theatre"}  # computed from real coordinates only


def _unique_ids(asm: Assembly, source: str, label: str, prop: str) -> dict[str, int]:
    ids = asm.ids_by_prop(source, label, prop)
    if len(ids) != len(asm.sources[source].nodes[label].frame):
        raise RuntimeError(f"{source}.{label}.{prop} is not unique; cannot use it as a join key")
    return ids


def _country_id(asm: Assembly, iso3: str) -> int:
    key = f"ISO3:{iso3}"
    if key not in asm.country_ids:
        raise RuntimeError(f"placement country {iso3} has no Country node (not in power_plants)")
    return asm.country_ids[key]


def add_located_in(asm: Assembly) -> None:
    sites = _unique_ids(asm, "supply_chain", "Site", "site_id")
    sups = _unique_ids(asm, "supply_chain", "Supplier", "supplier_id")
    for ids, placements in ((sites, asm.sites), (sups, asm.suppliers)):
        for p in placements:
            asm.builder.add_edge(ids[p.key], _country_id(asm, p.country_code), "LOCATED_IN",
                                 SYNTHETIC | {"method": "synthetic_placement"})
    by_country = Counter(p.country_code for p in asm.sites + asm.suppliers)
    print(f"[bridge] LOCATED_IN: {len(asm.sites)} Sites + {len(asm.suppliers)} Suppliers -> {dict(by_country)}")


def add_powered_by(asm: Assembly) -> None:
    plants = asm.sources["power_plants"].nodes["PowerPlant"].frame
    plant_ids = _unique_ids(asm, "power_plants", "PowerPlant", "gppd_idnr")
    links = powered_by(asm.sites + asm.suppliers, plants["gppd_idnr"].tolist(),
                       plants["latitude"].to_numpy(), plants["longitude"].to_numpy(),
                       cfg.POWERED_BY_K, cfg.POWERED_BY_MAX_KM)
    sites = _unique_ids(asm, "supply_chain", "Site", "site_id")
    sups = _unique_ids(asm, "supply_chain", "Supplier", "supplier_id")
    for link in links:
        src = sites[link.src] if link.src in sites else sups[link.src]
        asm.builder.add_edge(src, plant_ids[link.dst], "POWERED_BY", SYNTHETIC | {"distance_km": link.distance_km})
    per = Counter(link.src for link in links)
    short = {p.key: per.get(p.key, 0) for p in asm.sites + asm.suppliers if per.get(p.key, 0) < cfg.POWERED_BY_K}
    print(f"[bridge] POWERED_BY: {len(links)} edges ({len(asm.sites)} Sites, {len(asm.suppliers)} Suppliers, "
          f"k={cfg.POWERED_BY_K}, <= {cfg.POWERED_BY_MAX_KM:g} km); entities with fewer than k: {short or 'none'}")


def add_sources_from(asm: Assembly, rng: np.random.Generator) -> None:
    lr = asm.sources["logistics_risk"]
    lr_ids = _unique_ids(asm, "logistics_risk", "Supplier", "supplier_id")
    lr_raw = dict(zip(lr.nodes["Supplier"].frame["_id"], lr.nodes["Supplier"].frame["supplier_id"]))
    lr_by_country: dict[str, list[str]] = defaultdict(list)
    for src, dst in lr.edges["LOCATED_IN"].frame[["_src", "_dst"]].itertuples(index=False):
        lr_by_country[str(asm.tid("logistics_risk", dst))].append(lr_raw[src])

    sc_country = {p.key: str(_country_id(asm, p.country_code)) for p in asm.suppliers}
    links = sources_from(sc_country, lr_by_country, rng, cfg.SOURCES_FROM_MIN, cfg.SOURCES_FROM_MAX)
    sups = _unique_ids(asm, "supply_chain", "Supplier", "supplier_id")
    for link in links:
        asm.builder.add_edge(sups[link.src], lr_ids[link.dst], "SOURCES_FROM", SYNTHETIC)
    per = Counter(link.src for link in links)
    missing = sorted(set(sc_country) - set(per))
    print(f"[bridge] SOURCES_FROM: {len(links)} edges, k -> #suppliers {dict(sorted(Counter(per.values()).items()))}; "
          f"suppliers with no same-country logistics supplier: {missing or 'none'}")


def add_patrols(asm: Assembly) -> None:
    site = _unique_ids(asm, "supply_chain", "Site", "site_id")[cfg.PATROL_SITE]
    drones = asm.sources["drone_swarm"].nodes["Drone"].frame
    for sid in drones["_id"]:
        asm.builder.add_edge(asm.tid("drone_swarm", sid), site, "PATROLS", SYNTHETIC | {"mission": "ISR"})
    print(f"[bridge] PATROLS: {len(drones)} Drones -> {cfg.PATROL_SITE}")


def add_near(asm: Assembly) -> None:
    loc = asm.sources["poledb"].nodes["Location"].frame
    # Location.address is documented as the key but is not unique, so join on node identity instead.
    dup_addr = int(loc["address"].duplicated().sum())
    loc_keys = [str(t) for t in _theatre_ids(asm, "poledb", "Location")]
    plants = asm.sources["power_plants"].nodes["PowerPlant"].frame
    plant_ids = _unique_ids(asm, "power_plants", "PowerPlant", "gppd_idnr")
    site_ids = _unique_ids(asm, "supply_chain", "Site", "site_id")
    lat, lon = loc["latitude"].to_numpy(), loc["longitude"].to_numpy()

    to_sites = near_links(loc_keys, lat, lon, [s.key for s in asm.sites],
                          np.array([s.latitude for s in asm.sites]), np.array([s.longitude for s in asm.sites]),
                          cfg.NEAR_MAX_KM)
    to_plants = near_links(loc_keys, lat, lon, plants["gppd_idnr"].tolist(), plants["latitude"].to_numpy(),
                           plants["longitude"].to_numpy(), cfg.NEAR_MAX_KM)
    for link in to_sites:
        asm.builder.add_edge(int(link.src), site_ids[link.dst], "NEAR",
                             SYNTHETIC | {"distance_km": link.distance_km})
    for link in to_plants:
        asm.builder.add_edge(int(link.src), plant_ids[link.dst], "NEAR",
                             DERIVED | {"distance_km": link.distance_km})
    print(f"[bridge] NEAR (<= {cfg.NEAR_MAX_KM:g} km): Location->Site {len(to_sites)} "
          f"(per site {dict(Counter(link.dst for link in to_sites))}), Location->PowerPlant {len(to_plants)} "
          f"({len({link.dst for link in to_plants})} distinct plants); {dup_addr} duplicate Location addresses")


def _theatre_ids(asm: Assembly, source: str, label: str) -> list[int]:
    return [asm.tid(source, i) for i in asm.sources[source].nodes[label].frame["_id"]]


def add_asset_types(asm: Assembly) -> None:
    b = asm.builder
    type_ids = {a.asset_type_id: b.add_node(("AssetType",), SYNTHETIC | {
        "asset_type_id": a.asset_type_id, "name": a.name, "description": a.description},
        key=("AssetType", a.asset_type_id)) for a in ASSET_TYPES}

    attacks = asm.sources["attack_scenarios"].nodes["Attack"].frame
    hits: Counter[str] = Counter()
    unmatched = 0
    for sid, target, tags in zip(attacks["_id"], attacks["target_type"], attacks["tags"]):
        matches = match_asset_types(target if isinstance(target, str) else None,
                                    tags if isinstance(tags, str) else None)
        unmatched += not matches
        for asset_id, keyword in matches:
            b.add_edge(asm.tid("attack_scenarios", sid), type_ids[asset_id], "TARGETS",
                       SYNTHETIC | {"keyword": keyword})
            hits[asset_id] += 1
    print(f"[bridge] TARGETS: {sum(hits.values())} edges from {len(attacks) - unmatched}/{len(attacks)} Attacks; "
          f"per AssetType {dict(hits)}")

    kinds = {
        "PowerPlant": _theatre_ids(asm, "power_plants", "PowerPlant"),
        "Site": _theatre_ids(asm, "supply_chain", "Site"),
        "PartSupplier": _theatre_ids(asm, "supply_chain", "Supplier"),
        "LogisticsSupplier": _theatre_ids(asm, "logistics_risk", "Supplier"),
        "Drone": _theatre_ids(asm, "drone_swarm", "Drone"),
    }
    runs: Counter[str] = Counter()
    for kind, tids in kinds.items():
        for tid in tids:
            for asset_id in RUNS_BY_KIND[kind]:
                b.add_edge(tid, type_ids[asset_id], "RUNS", SYNTHETIC)
                runs[kind] += 1
    print(f"[bridge] RUNS: {sum(runs.values())} edges {dict(runs)}")


def add_deep_powered_by(asm: Assembly) -> None:
    """supply_chain_deep facilities draw power from their k nearest plants (<= max km), like Sites do, so a
    power-plant loss can cascade into the deep supplier network."""
    if cfg.DEEP not in asm.sources:
        return
    plants = asm.sources["power_plants"].nodes["PowerPlant"].frame
    plant_ids = _unique_ids(asm, "power_plants", "PowerPlant", "gppd_idnr")
    plant_keys = plants["gppd_idnr"].tolist()
    p_lat, p_lon = plants["latitude"].to_numpy(), plants["longitude"].to_numpy()
    fac = asm.sources[cfg.DEEP].nodes["Facility"].frame
    edges, unpowered = 0, 0
    for sid in fac["_id"]:
        tid = asm.tid(cfg.DEEP, sid)
        props = asm.builder.nodes[tid].props
        hits = nearest_within(float(props["latitude"]), float(props["longitude"]), p_lat, p_lon,
                              cfg.POWERED_BY_K, cfg.POWERED_BY_MAX_KM)
        unpowered += not hits
        for m in hits:
            asm.builder.add_edge(tid, plant_ids[plant_keys[m.index]], "POWERED_BY",
                                 SYNTHETIC | {"distance_km": round(m.distance_km, 3)})
            edges += 1
    print(f"[bridge] POWERED_BY: {edges} edges from {len(fac)} deep Facilities (k={cfg.POWERED_BY_K}, "
          f"<= {cfg.POWERED_BY_MAX_KM:g} km); facilities with no plant in range: {unpowered}")


def add_synthetic_links(asm: Assembly, rng: np.random.Generator) -> None:
    add_located_in(asm)
    add_powered_by(asm)
    add_deep_powered_by(asm)
    add_sources_from(asm, rng)
    add_patrols(asm)
    add_near(asm)
    add_asset_types(asm)
