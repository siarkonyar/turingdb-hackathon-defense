"""Synthetic bridges between datasets that share no keys. Every function is deterministic
given its inputs and the numpy Generator it is handed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from geo import jitter, nearest_within, pairs_within, xy_to_latlon


@dataclass(frozen=True)
class Placement:
    key: str
    place: str
    country_code: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Link:
    src: str
    dst: str
    distance_km: float | None = None


def place_sites(sites: dict[str, tuple[str, str, float, float]], rng: np.random.Generator,
                jitter_km: float) -> list[Placement]:
    out = []
    for site_id in sorted(sites):
        place, iso3, lat, lon = sites[site_id]
        jlat, jlon = jitter(lat, lon, rng, jitter_km)
        out.append(Placement(site_id, place, iso3, round(jlat, 6), round(jlon, 6)))
    return out


def place_suppliers(supplier_ids: list[str], towns: tuple[tuple[str, str, float, float], ...],
                    rng: np.random.Generator, jitter_km: float) -> list[Placement]:
    if len(supplier_ids) > len(towns):
        raise ValueError(f"{len(supplier_ids)} suppliers but only {len(towns)} towns")
    order = rng.permutation(len(towns))
    out = []
    for sup_id, town_idx in zip(sorted(supplier_ids), order):
        place, iso3, lat, lon = towns[town_idx]
        jlat, jlon = jitter(lat, lon, rng, jitter_km)
        out.append(Placement(sup_id, place, iso3, round(jlat, 6), round(jlon, 6)))
    return out


def powered_by(points: list[Placement], plant_ids: list[str], plant_lat: np.ndarray, plant_lon: np.ndarray,
               k: int, max_km: float) -> list[Link]:
    links = []
    for p in points:
        for m in nearest_within(p.latitude, p.longitude, plant_lat, plant_lon, k, max_km):
            links.append(Link(p.key, plant_ids[m.index], round(m.distance_km, 3)))
    return links


def sources_from(sc_country: dict[str, str], lr_by_country: dict[str, list[str]], rng: np.random.Generator,
                 k_min: int, k_max: int) -> list[Link]:
    """Each supply_chain supplier sources from k_min..k_max logistics_risk suppliers in its own country."""
    links = []
    for sc_id in sorted(sc_country):
        pool = sorted(lr_by_country.get(sc_country[sc_id], []))
        if not pool:
            continue
        k = min(int(rng.integers(k_min, k_max + 1)), len(pool))
        for idx in sorted(rng.choice(len(pool), size=k, replace=False)):
            links.append(Link(sc_id, pool[int(idx)]))
    return links


def near_links(src_ids: list[str], src_lat: np.ndarray, src_lon: np.ndarray,
               dst_ids: list[str], dst_lat: np.ndarray, dst_lon: np.ndarray, max_km: float) -> list[Link]:
    pairs = pairs_within(src_lat, src_lon, dst_lat, dst_lon, max_km)
    return [Link(src_ids[i], dst_ids[j], round(d, 3)) for i, j, d in sorted(pairs)]


def project_swarm(x: np.ndarray, y: np.ndarray, centre: Placement, metres_per_unit: float,
                  origin_xy: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    coords = [xy_to_latlon(float(a), float(b), centre.latitude, centre.longitude, metres_per_unit, origin_xy)
              for a, b in zip(x, y)]
    lat = np.round(np.array([c[0] for c in coords]), 7)
    lon = np.round(np.array([c[1] for c in coords]), 7)
    return lat, lon
