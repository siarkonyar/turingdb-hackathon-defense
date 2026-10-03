"""The deep capability model on a tiny hand-built network (no TuringDB).

    platform P (weight 1) <- system S <- component C <- material M (CHN 80%, AUS 20%)
    P made at prime F0 (USA), C made at fab F1 (DEU, share 100) and F2 (CHN, share 0 -> counted as 1)
    F0 ships via port USA1, F1 via DEU1; DEU1's sea shipments: 50% through chokepoint K
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agents import deep_impact as D


def fac(fid, cc, ftype="component fab", lat=50.0, lon=8.0):
    return {"facility_id": fid, "name": fid, "type": ftype, "cc": cc, "lat": lat, "lon": lon, "utilization": 0.5}


@pytest.fixture
def static() -> D.Static:
    s = D.Static(
        platforms={"P": ("PLT1", "Drone", 1.0)},
        children={"P": ("S",), "S": ("C",), "C": ("M",)},
        items={"P": ("PLT1", "Drone", "Platform"), "S": ("SYS1", "Sys", "System"), "C": ("CMP1", "Chip", "Component"),
               "M": ("MAT1", "Gallium", "Material")},
        country_share={"M": {"CHN": 80.0, "AUS": 20.0}},
        port_choke={"DEU1": {"K": 0.5}},
        facilities={"F0": fac("FAC0", "USA", "final assembly plant", 40.0, -75.0), "F1": fac("FAC1", "DEU"),
                    "F2": fac("FAC2", "CHN", lat=31.0, lon=121.0), "F3": fac("FAC3", "FRA")},
        ports={"USA1": {"port_id": "USNYC", "name": "NY", "cc": "USA", "lat": 40.7, "lon": -74.0},
               "DEU1": {"port_id": "DEHAM", "name": "Hamburg", "cc": "DEU", "lat": 53.5, "lon": 10.0},
               "DEU2": {"port_id": "DEBRV", "name": "Bremerhaven", "cc": "DEU", "lat": 53.5, "lon": 8.6},
               "NLD1": {"port_id": "NLRTM", "name": "Rotterdam", "cc": "NLD", "lat": 51.9, "lon": 4.5}},
        chokes={"K": {"waypoint_id": "DOVER", "name": "Dover", "lat": 51.0, "lon": 1.4}},
        countries={}, powered_main=frozenset({"F1"}),
        ships_main={"F0": frozenset({"USA1"}), "F1": frozenset({"DEU1"})},
        allied=frozenset({"USA", "DEU", "FRA", "NLD"}))
    return replace(s, item_weight=D.item_weights(s), order=tuple(D._bottom_up(s)))


@pytest.fixture
def state() -> D.State:
    return D.State(facilities=frozenset({"F0", "F1", "F2", "F3"}), ports=frozenset({"USA1", "DEU1", "DEU2", "NLD1"}),
                   produced_at={"P": (("F0", 100.0),), "C": (("F1", 100.0), ("F2", 0.0))},
                   ships_via={"F0": ("USA1",), "F1": ("DEU1",)}, powered=frozenset({"F1"}))


def loss(static, state) -> float:
    return round(D.evaluate(static, state).loss, 4)


def buffered(shortfall: float, tiers: int) -> float:
    """Platform loss when an item `tiers` levels below the platform loses `shortfall` of its output."""
    for _ in range(tiers):
        shortfall *= 1 - D.TIER_BUFFER
    return round(shortfall, 4)


def test_baseline_is_zero(static, state):
    assert loss(static, state) == 0.0


def test_a_closed_port_leaves_the_overland_floor(static, state):
    c_short = (1 - D.OVERLAND_FLOOR) * 100 / 101  # F1 makes 100 of C's 101 share points; C is 2 tiers below P
    assert loss(static, D.with_changes(state, closed={"DEU1"})) == buffered(c_short, 2)


def test_a_reroute_recovers_most_but_not_all(static, state):
    closed = D.with_changes(state, closed={"DEU1"})
    alts, users = D.reroute_plan(static, closed, "DEU1")
    assert users == ["F1"] and alts[0] == "DEU2"  # best factor ties are broken by same country first
    moved = replace(closed, ships_via={**closed.ships_via, "F1": ("DEU1", "DEU2")})
    assert D.facility_ok(static, moved, "F1") == pytest.approx(D.ALT_PORT_EFFICIENCY)
    assert 0 < loss(static, moved) < loss(static, closed)


def test_reroutes_spread_over_several_ports(static, state):
    busy = replace(state, ships_via={**state.ships_via, "F2": ("DEU1",), "F3": ("DEU1",)})
    alts, users = D.reroute_plan(static, D.with_changes(busy, closed={"DEU1"}), "DEU1")
    assignment = D.reroute_assignment(alts, users)
    assert len(users) == 3 and len(set(assignment.values())) == 3  # no new single export port


def test_a_blocked_chokepoint_costs_its_share_of_the_flow(static, state):
    ok = D.facility_ok(static, D.with_changes(state, blocked={"K"}), "F1")
    assert ok == pytest.approx(1 - D.REROUTE_LOSS * 0.5)


def test_export_controls_cut_that_country_share(static, state):
    assert loss(static, D.with_changes(state, controls={"CHN|M"})) == buffered(0.8, 3)  # CHN made 80% of M


def test_stockpile_floor_caps_the_shortfall(static, state):
    hit = D.with_changes(state, controls={"CHN|M"})
    assert loss(static, D.with_changes(hit, stockpiled={"M"})) == buffered(1 - D.STOCKPILE_FLOOR, 3)


def test_a_lost_power_feed_stops_a_facility(static, state):
    assert D.facility_ok(static, replace(state, powered=frozenset()), "F1") == 0.0


def test_prime_outage_hits_the_platform_and_replacement_prefers_allies(static, state):
    out = D.with_changes(state, closed={"F0"})
    assert loss(static, out) == 1.0
    assert D.replacement_plan(static, out, "F0", D.evaluate(static, out).facility_ok) == {}  # no other prime
    fab_out = D.with_changes(state, closed={"F1"})
    plan = D.replacement_plan(static, fab_out, "F1", D.evaluate(static, fab_out).facility_ok)
    assert plan == {"C": "F3"}  # same facility type; allied FRA chosen (F2 already makes C)


def test_item_weights_flow_down_the_bill_of_materials(static):
    assert static.item_weight == {"P": 1.0, "S": 1.0, "C": 1.0, "M": 1.0}
    assert list(static.order) == ["M", "C", "S", "P"]


def test_deleted_makers_keep_their_lost_share(static, state):
    static = replace(static, original_makers=state.produced_at)
    deleted = replace(state, facilities=state.facilities - {"F1"},
                      produced_at={**state.produced_at, "C": (("F2", 0.0),)})
    assert loss(static, deleted) == buffered(100 / 101, 2)
    # A deleted sole prime has no PRODUCED_AT edges left; it must not regain full output.
    deleted = replace(state, facilities=state.facilities - {"F0"},
                      produced_at={"C": state.produced_at["C"]})
    assert loss(static, deleted) == 1.0
