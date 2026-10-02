"""Pure-logic units: ref parsing, node normalisation, cascade walk/arcs/KPIs, diffing."""

from __future__ import annotations

import math

import pytest

from api import cascade
from api.backends.base import merge_status
from api.diffing import diff_snapshots
from api.main import parse_until
from api.models import Affected, Node
from api.nodes import make_node, plant_importance, with_status
from api.refs import Ref, parse_bbox, parse_kinds, parse_ref


def node(nid: str, label: str, lat: float | None = 1.0, lon: float | None = 1.0, **kw) -> Node:
    return make_node(nid, label, {"name": nid, "latitude": lat, "longitude": lon, **kw})


# ------------------------------------------------------------------ refs

@pytest.mark.parametrize("raw,expected", [
    (None, Ref("main")), ("main", Ref("main")), ("4", Ref("4")), ("0", Ref("0")),
    ("main@abcd1234", Ref("main", "abcd1234")), ("12@ffff", Ref("12", "ffff")),
])
def test_parse_ref_accepts_branches_and_commits(raw, expected):
    assert parse_ref(raw) == expected


@pytest.mark.parametrize("raw", ["dev", "4; DROP", "main@XYZ", "-1", "main@ab"])
def test_parse_ref_rejects_anything_that_could_reach_cypher(raw):
    with pytest.raises(ValueError):
        parse_ref(raw)


def test_parse_bbox_and_antimeridian_contains():
    box = parse_bbox("170,-10,-170,10")
    assert box.contains(175, 0) and box.contains(-175, 0) and not box.contains(0, 0)
    assert parse_bbox(None) is None
    for bad in ("1,2,3", "a,b,c,d", "0,80,10,95"):
        with pytest.raises(ValueError):
            parse_bbox(bad)


def test_parse_kinds_dedupes_and_validates():
    assert parse_kinds("plant,site,plant", ("plant", "site")) == ("plant", "site")
    assert parse_kinds(None, ("plant",)) == ("plant",)
    with pytest.raises(ValueError):
        parse_kinds("tank", ("plant",))


def test_parse_until_normalises_to_utc_z():
    assert parse_until("2026-09-29T07:00:00+02:00") == "2026-09-29T05:00:00Z"
    assert parse_until("2026-09-29T05:00:00Z") == "2026-09-29T05:00:00Z"
    assert parse_until(None) is None
    with pytest.raises(ValueError):
        parse_until("yesterday")


# ------------------------------------------------------------------ nodes

def test_make_node_maps_kind_status_and_drops_nan():
    n = make_node(7, "PowerPlant", {"name": "X", "latitude": 1.5, "longitude": math.nan, "capacity_mw": 4000.0,
                                    "ops_status": "at_risk", "primary_fuel": "Nuclear", "geo_synthetic": True})
    assert (n.id, n.kind, n.status, n.fuel, n.lon, n.synthetic) == ("7", "plant", "at_risk", "Nuclear", None, True)
    assert n.importance == pytest.approx(1.0)


def test_make_node_falls_back_to_type_then_label_for_name():
    assert make_node(1, "Crime", {"type": "Burglary"}).name == "Burglary"
    assert make_node(2, "Thing", {}).name == "Thing 2"
    assert make_node(3, "Thing", {}).kind == "other"


def test_unknown_status_is_ignored_and_importance_is_clamped():
    assert make_node(1, "Site", {"ops_status": "on fire"}).status is None
    assert plant_importance(None) == 0.05 and plant_importance(1e9) == 1.0
    assert with_status(node("a", "Site"), "bogus").status is None


def test_merge_status_only_escalates():
    assert merge_status(None, "at_risk") == "at_risk"
    assert merge_status("no_power", "at_risk") == "no_power"
    assert merge_status("at_risk", "no_power") == "no_power"


# ------------------------------------------------------------------ cascade

class FakeSource:
    def __init__(self, edges: dict[tuple[str, str], list[Node]]):
        self.edges, self.calls = edges, []

    def dependents(self, label, ids, rule):
        self.calls.append((label, tuple(ids), rule))
        return [cascade.Dependency(i, child, rule) for i in ids for child in self.edges.get((i, rule), [])]


def test_walk_follows_rules_by_label_and_reports_shortest_hop():
    plant, site, drone = node("p", "PowerPlant"), node("s", "Site"), node("d", "Drone")
    src = FakeSource({("p", "POWERED_BY"): [site], ("s", "PATROLS"): [drone, site]})
    affected = cascade.walk(plant, src)
    assert [(a.node.id, a.hop, a.via, a.parent_id) for a in affected] == [("s", 1, "POWERED_BY", "p"),
                                                                         ("d", 2, "PATROLS", "s")]
    assert all(call[0] != "Drone" for call in src.calls)  # drones have no dependents rule


def test_walk_stops_at_max_hops_and_never_revisits_struck():
    a, b = node("a", "Site"), node("b", "Site")
    src = FakeSource({("a", "PATROLS"): [b], ("b", "PATROLS"): [a]})
    assert [x.node.id for x in cascade.walk(a, src, max_hops=5)] == ["b"]


def test_build_arcs_collapses_unlocated_hops():
    sup, part, site = node("u", "Supplier"), node("x", "Part", lat=None, lon=None), node("s", "Site", 2.0, 3.0)
    affected = [Affected(node=part, hop=1, via="SUPPLIED_BY", parent_id="u"),
                Affected(node=site, hop=2, via="DELIVERED_TO", parent_id="x")]
    arcs = cascade.build_arcs(sup, affected)
    assert len(arcs) == 1
    assert (arcs[0].source_id, arcs[0].target_id, arcs[0].target, arcs[0].hop) == ("u", "s", (3.0, 2.0), 2)


def test_statuses_and_kpis():
    affected = [Affected(node=node("s", "Site"), hop=1, via="POWERED_BY", parent_id="p"),
                Affected(node=node("u", "Supplier"), hop=1, via="POWERED_BY", parent_id="p"),
                Affected(node=node("x", "Part", lat=None, lon=None), hop=2, via="SUPPLIED_BY", parent_id="u")]
    assert cascade.powered_ids(affected) == ["s", "u"]
    marked = cascade.apply_statuses(affected, unpowered={"s"})
    assert [a.node.status for a in marked] == ["no_power", "at_risk", "at_risk"]
    k = cascade.kpis(a.node for a in marked)
    assert (k.assets_at_risk, k.sites_without_power, k.suppliers_without_power, k.parts_affected) == (1, 1, 0, 1)


# ------------------------------------------------------------------ diff

def test_diff_snapshots_reports_added_removed_and_changed_fields():
    a = {"1": node("1", "Site"), "2": node("2", "Site")}
    b = {"2": with_status(node("2", "Site"), "at_risk"), "3": node("3", "Site")}
    added, removed, changed = diff_snapshots(a, b)
    assert [n.id for n in added] == ["3"] and [n.id for n in removed] == ["1"]
    assert changed[0].node.id == "2" and changed[0].fields == {"status": (None, "at_risk")}
