"""Verify demo data semantics, isolation, independent recovery and import format."""
from __future__ import annotations

import json

import pytest

from datasets.dover.model import PLACES, build_corridor
from datasets.dover.validate import validate


@pytest.fixture(scope="module")
def corridor():
    return build_corridor()


def test_integrity_and_cascade(corridor):
    report = validate(corridor)
    assert report["display_cascade_degrees"] == 12
    assert report["strait_display_affected_facilities"] >= 700


def test_reproducible_jsonl(corridor, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    corridor.graph.write_jsonl(a)
    build_corridor().graph.write_jsonl(b)
    assert a.read_bytes() == b.read_bytes()
    rows = [json.loads(line) for line in a.read_text().splitlines()]
    nodes = [r for r in rows if r["type"] == "node"]
    assert [r["id"] for r in nodes] == [str(i) for i in range(len(nodes))]
    node_ids = {n["id"] for n in nodes}
    assert all(r["start"]["id"] in node_ids
               and r["end"]["id"] in node_ids
               for r in rows if r["type"] == "relationship")


def test_london_loss_includes_resources_but_not_paris(corridor):
    g, ids = corridor.graph, corridor.ids
    disabled = [g.nodes[e.end] for e in g.edges
                if e.start == ids["scenario:london_loss"] and e.edge_type == "DISABLES"]
    assert disabled and all(n.props["region"] == "London" for n in disabled)
    assert {"Facility", "PowerPlant", "Stockpile", "ResourcePool"} <= {n.labels[0] for n in disabled}
    assert "stock:london" in {n.props["entity_id"] for n in disabled}
    assert "airport:paris" not in {n.props["entity_id"] for n in disabled}


def test_kent_power_is_grid_loss_not_destruction(corridor):
    g, ids = corridor.graph, corridor.ids
    targets = [g.nodes[e.end] for e in g.edges if e.start == ids["scenario:kent_power"]]
    assert len(targets) == sum(p[2] == "Kent" for p in PLACES)
    assert all(n.labels == ("PowerPlant",) for n in targets)
    # Hospitals remain nodes and have alternatives that consume finite resources.
    hospital = ids["mission:ashford:military_hospital"]
    options = [g.nodes[e.end] for e in g.edges if e.start == hospital and e.edge_type == "HAS_RECOVERY"]
    assert {n.props["recovery_kind"] for n in options} >= {"mobile_power", "relocate_service"}


def test_second_sources_leave_affected_region(corridor):
    g = corridor.graph
    by_option = {e.end: e.start for e in g.edges if e.edge_type == "HAS_RECOVERY"}
    for i, n in enumerate(g.nodes):
        if n.labels == ("RecoveryOption",) and n.props["recovery_kind"] in ("second_source", "relocate_service"):
            providers = [g.nodes[e.end] for e in g.edges if e.start == i and e.edge_type == "REQUIRES"]
            target = g.nodes[by_option[i]]
            assert all(p.props["region"] != target.props["region"] for p in providers)
            assert all(p.props["country_code"] == target.props["country_code"] for p in providers)


def test_air_capacity_is_shared_and_smaller_than_demand(corridor):
    g, ids = corridor.graph, corridor.ids
    for key in ("london_paris_air", "kent_beauvais_air"):
        route = g.nodes[ids[f"route:{key}"]]
        assert route.props["capacity_shared_directions"] is True
        assert route.props["capacity_tonnes_day"] == 64.0
        assert route.props["capacity_tonnes_day"] < 1240.2
