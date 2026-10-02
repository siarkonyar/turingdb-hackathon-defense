import numpy as np
import pytest

from bridges import Placement, near_links, place_sites, place_suppliers, powered_by, project_swarm, sources_from
from geo import haversine_km, jitter, nearest_within, offset_latlon, pairs_within, xy_to_latlon


def test_haversine_london_paris_is_about_344_km():
    assert haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(343.5, abs=1.0)


def test_haversine_zero_for_same_point():
    assert haversine_km(53.0, -2.0, 53.0, -2.0) == pytest.approx(0.0)


def test_nearest_within_orders_by_distance_and_applies_radius():
    lat = np.array([53.0, 53.1, 53.01, 60.0])
    lon = np.array([-2.0, -2.0, -2.0, -2.0])
    matches = nearest_within(53.0, -2.0, lat, lon, k=3, max_km=50)
    assert [m.index for m in matches] == [0, 2, 1]
    assert all(m.distance_km <= 50 for m in matches)


def test_nearest_within_returns_fewer_than_k_when_out_of_range():
    matches = nearest_within(0.0, 0.0, np.array([10.0]), np.array([10.0]), k=3, max_km=50)
    assert matches == []


def test_pairs_within_matches_brute_force():
    rng = np.random.default_rng(1)
    a_lat, a_lon = 53.4 + rng.random(50) * 0.2, -2.4 + rng.random(50) * 0.2
    b_lat, b_lon = 53.0 + rng.random(300) * 1.0, -3.0 + rng.random(300) * 1.5
    got = {(i, j) for i, j, _ in pairs_within(a_lat, a_lon, b_lat, b_lon, max_km=5, chunk=7)}
    dist = haversine_km(a_lat[:, None], a_lon[:, None], b_lat[None, :], b_lon[None, :])
    want = {(int(i), int(j)) for i, j in zip(*np.nonzero(dist <= 5))}
    assert got == want and got


def test_pairs_within_empty_inputs():
    assert pairs_within(np.array([]), np.array([]), np.array([1.0]), np.array([1.0]), 5) == []


def test_offset_and_projection_round_trip():
    lat, lon = offset_latlon(53.0, -2.0, north_m=1000, east_m=0)
    assert haversine_km(53.0, -2.0, lat, lon) == pytest.approx(1.0, abs=0.01)
    assert xy_to_latlon(50, 50, 53.0, -2.0, 20.0, (50, 50)) == pytest.approx((53.0, -2.0))


def test_jitter_stays_inside_radius():
    rng = np.random.default_rng(7)
    for _ in range(200):
        lat, lon = jitter(50.0, 10.0, rng, max_km=2.0)
        assert haversine_km(50.0, 10.0, lat, lon) <= 2.0 + 1e-6


def test_place_suppliers_is_deterministic_and_bijective():
    towns = tuple((f"T{i}", "GBR", 50.0 + i, -1.0) for i in range(5))
    first = place_suppliers(["S3", "S1", "S2"], towns, np.random.default_rng(42), 1.0)
    second = place_suppliers(["S1", "S2", "S3"], towns, np.random.default_rng(42), 1.0)
    assert first == second
    assert [p.key for p in first] == ["S1", "S2", "S3"]
    assert len({p.place for p in first}) == 3


def test_place_suppliers_rejects_too_few_towns():
    with pytest.raises(ValueError):
        place_suppliers(["A", "B"], (("T", "GBR", 0.0, 0.0),), np.random.default_rng(0), 1.0)


def test_place_sites_sorted_and_jittered_close_to_anchor():
    sites = {"B": ("b", "FRA", 45.0, 1.0), "A": ("a", "GBR", 53.0, -2.0)}
    placed = place_sites(sites, np.random.default_rng(0), jitter_km=1.5)
    assert [p.key for p in placed] == ["A", "B"]
    assert haversine_km(53.0, -2.0, placed[0].latitude, placed[0].longitude) <= 1.5 + 1e-6


def test_powered_by_k_nearest_within_radius():
    p = Placement("SITE", "x", "GBR", 53.0, -2.0)
    plant_lat = np.array([53.0, 53.01, 53.02, 53.03, 55.0])
    plant_lon = np.full(5, -2.0)
    links = powered_by([p], ["P0", "P1", "P2", "P3", "FAR"], plant_lat, plant_lon, k=3, max_km=50)
    assert [link.dst for link in links] == ["P0", "P1", "P2"]
    assert links[0].distance_km == 0.0


def test_sources_from_respects_country_and_bounds():
    sc_country = {"S1": "GBR", "S2": "FRA", "S3": "XXX"}
    lr = {"GBR": ["g1", "g2", "g3", "g4"], "FRA": ["f1"]}
    links = sources_from(sc_country, lr, np.random.default_rng(3), 1, 3)
    by_src: dict[str, list[str]] = {}
    for link in links:
        by_src.setdefault(link.src, []).append(link.dst)
    assert set(by_src) == {"S1", "S2"}  # S3 has no same-country pool
    assert 1 <= len(by_src["S1"]) <= 3 and all(d.startswith("g") for d in by_src["S1"])
    assert by_src["S2"] == ["f1"]
    assert links == sources_from(sc_country, lr, np.random.default_rng(3), 1, 3)


def test_near_links_uses_ids():
    links = near_links(["L0", "L1"], np.array([53.0, 54.0]), np.array([-2.0, -2.0]),
                       ["X"], np.array([53.001]), np.array([-2.0]), max_km=5)
    assert [(link.src, link.dst) for link in links] == [("L0", "X")]


def test_project_swarm_centres_on_site():
    centre = Placement("SITE01", "x", "GBR", 53.47, -2.31)
    lat, lon = project_swarm(np.array([50.0, 100.0]), np.array([50.0, 50.0]), centre, 20.0, (50.0, 50.0))
    assert lat[0] == pytest.approx(53.47) and lon[0] == pytest.approx(-2.31)
    assert haversine_km(lat[0], lon[0], lat[1], lon[1]) == pytest.approx(1.0, abs=0.01)
