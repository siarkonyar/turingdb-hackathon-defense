"""Geospatial helpers: great-circle distance, nearest-neighbour joins, synthetic placement."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EARTH_RADIUS_KM = 6371.0088
METRES_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Match:
    """One spatial match: index into the candidate array and its distance."""

    index: int
    distance_km: float


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Accepts scalars or numpy arrays (broadcasts)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def nearest_within(lat: float, lon: float, cand_lat: np.ndarray, cand_lon: np.ndarray,
                   k: int, max_km: float) -> list[Match]:
    """The k nearest candidates to (lat, lon) that lie within max_km, closest first."""
    dist = haversine_km(lat, lon, cand_lat, cand_lon)
    order = np.argsort(dist, kind="stable")[:k]
    return [Match(int(i), float(dist[i])) for i in order if dist[i] <= max_km]


def pairs_within(a_lat: np.ndarray, a_lon: np.ndarray, b_lat: np.ndarray, b_lon: np.ndarray,
                 max_km: float, chunk: int = 2048) -> list[tuple[int, int, float]]:
    """All (i, j, distance_km) with dist(a[i], b[j]) <= max_km.

    b is pre-filtered to the bounding box of a (padded by max_km) so the dense
    distance matrix stays small even when b is the global power-plant table.
    """
    if len(a_lat) == 0 or len(b_lat) == 0:
        return []
    pad_lat = max_km / (METRES_PER_DEG_LAT / 1000)
    max_abs_lat = min(float(np.max(np.abs(a_lat))) + pad_lat, 89.0)
    pad_lon = pad_lat / math.cos(math.radians(max_abs_lat))
    in_box = ((b_lat >= a_lat.min() - pad_lat) & (b_lat <= a_lat.max() + pad_lat)
              & (b_lon >= a_lon.min() - pad_lon) & (b_lon <= a_lon.max() + pad_lon))
    b_idx = np.nonzero(in_box)[0]
    if len(b_idx) == 0:
        return []
    out: list[tuple[int, int, float]] = []
    for start in range(0, len(a_lat), chunk):
        sl = slice(start, start + chunk)
        dist = haversine_km(a_lat[sl, None], a_lon[sl, None], b_lat[None, b_idx], b_lon[None, b_idx])
        ii, jj = np.nonzero(dist <= max_km)
        out.extend((start + int(i), int(b_idx[j]), float(dist[i, j])) for i, j in zip(ii, jj))
    return out


def offset_latlon(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by metres north/east (flat-earth approximation, fine below ~50 km)."""
    new_lat = lat + north_m / METRES_PER_DEG_LAT
    new_lon = lon + east_m / (METRES_PER_DEG_LAT * math.cos(math.radians(lat)))
    return new_lat, new_lon


def jitter(lat: float, lon: float, rng: np.random.Generator, max_km: float) -> tuple[float, float]:
    """Displace a point uniformly within a disc of radius max_km."""
    radius_m = max_km * 1000 * math.sqrt(rng.random())
    bearing = 2 * math.pi * rng.random()
    return offset_latlon(lat, lon, radius_m * math.cos(bearing), radius_m * math.sin(bearing))


def xy_to_latlon(x: float, y: float, centre_lat: float, centre_lon: float,
                 metres_per_unit: float, origin_xy: tuple[float, float]) -> tuple[float, float]:
    """Project local swarm coordinates (x east, y north) onto lat/lon around a centre point."""
    east_m = (x - origin_xy[0]) * metres_per_unit
    north_m = (y - origin_xy[1]) * metres_per_unit
    return offset_latlon(centre_lat, centre_lon, north_m, east_m)
