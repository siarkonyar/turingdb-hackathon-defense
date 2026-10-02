import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from assets import ASSET_TYPE_IDS, RUNS_BY_KIND, match_asset_types
from countries import merge_countries, normalise_name
from docblock import splice_block
from enrich import centroid_coords, inherit_coords, ts_from_dmy, ts_from_step, ts_from_ymd
from graph_model import GraphBuilder, clean_props


# ---------------------------------------------------------------- countries

def test_normalise_name_handles_aliases_case_and_accents():
    assert normalise_name("UK") == "united kingdom"
    assert normalise_name(" North  Macedonia ") == "macedonia"
    assert normalise_name("Côte d'Ivoire") == "cote d ivoire"


def test_merge_countries_matches_aliases_and_reports_unmatched():
    pp = [("GBR", "United Kingdom"), ("FRA", "France"), ("USA", "United States of America")]
    merge = merge_countries(pp, ["UK", "France", "Haiti"])
    assert merge.unmatched_lr == ("Haiti",)
    assert merge.lr_name_to_key == {"UK": "ISO3:GBR", "France": "ISO3:FRA", "Haiti": "NAME:Haiti"}
    by_key = {c.key: c for c in merge.countries}
    assert by_key["ISO3:GBR"].sources == ("power_plants", "logistics_risk")
    assert by_key["ISO3:USA"].sources == ("power_plants",)
    assert by_key["NAME:Haiti"].country_code is None
    assert len(merge.countries) == 4


# ---------------------------------------------------------------- assets

@pytest.mark.parametrize("target, tags, expected", [
    ("PLC", None, "ICS_SCADA"),
    ("Windows Host", None, "CORPORATE_IT"),
    ("GitHub Actions", "ci/cd, secrets", "SW_SUPPLY_CHAIN"),
    ("GPS Receivers", None, "SATCOM_GNSS"),
    (None, "drone, hijack", "UAS_AVIONICS"),
    ("Smart Lock", "rfid, badge", "PHYSICAL_ACCESS"),
])
def test_match_asset_types_hits(target, tags, expected):
    assert expected in {a for a, _ in match_asset_types(target, tags)}


def test_match_asset_types_respects_word_boundaries():
    assert match_asset_types("Robot vacuum", "port scanning, botnet") == []
    assert match_asset_types(None, None) == []


def test_runs_reference_known_asset_types():
    assert all(a in ASSET_TYPE_IDS for kinds in RUNS_BY_KIND.values() for a in kinds)


# ---------------------------------------------------------------- graph builder

def test_clean_props_drops_nulls_and_unwraps_numpy():
    props = clean_props({"a": None, "b": float("nan"), "c": pd.NA, "d": np.int64(3), "e": np.float64(1.5),
                         "f": np.bool_(True), "g": "x"})
    assert props == {"d": 3, "e": 1.5, "f": True, "g": "x"}
    assert type(props["d"]) is int


def test_clean_props_rejects_unsupported_types():
    with pytest.raises(TypeError):
        clean_props({"bad": [1, 2]})


def test_builder_writes_contiguous_apoc_jsonl(tmp_path):
    b = GraphBuilder()
    a = b.add_node(("Site",), {"site_id": "S1", "lat": None}, key=("Site", "S1"))
    p = b.add_node(("PowerPlant",), {"gppd_idnr": "P1"})
    b.add_edge(a, p, "POWERED_BY", {"distance_km": 1.234})
    out = tmp_path / "g.jsonl"
    b.write_jsonl(out)
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [n["id"] for n in lines if n["type"] == "node"] == ["0", "1"]
    assert lines[0]["properties"] == {"site_id": "S1"}
    assert lines[2] == {"type": "relationship", "id": "0", "label": "POWERED_BY", "start": {"id": "0"},
                        "end": {"id": "1"}, "properties": {"distance_km": 1.234}}
    assert b.node_id(("Site", "S1")) == a
    assert b.label_counts() == {"Site": 1, "PowerPlant": 1} and b.edge_counts() == {"POWERED_BY": 1}


def test_builder_guards_bad_input():
    b = GraphBuilder()
    b.add_node(("A",), {}, key=("A", "1"))
    with pytest.raises(ValueError):
        b.add_node(("A",), {}, key=("A", "1"))
    with pytest.raises(ValueError):
        b.add_node((), {})
    with pytest.raises(ValueError):
        b.add_edge(0, 5, "X")


# ---------------------------------------------------------------- enrichment

def test_timestamps():
    assert ts_from_ymd("2024-12-16") == {"timestamp": "2024-12-16T00:00:00Z", "ts_epoch": 1734307200}
    assert ts_from_dmy("21/08/2017", "20:32")["timestamp"] == "2017-08-21T20:32:00Z"
    assert ts_from_dmy("21/08/2017")["timestamp"] == "2017-08-21T00:00:00Z"
    assert ts_from_ymd("not a date") == {} and ts_from_ymd(None) == {} and ts_from_dmy(float("nan")) == {}
    start = datetime(2026, 9, 29, 5, tzinfo=timezone.utc)
    assert ts_from_step(12, start, 5)["timestamp"] == "2026-09-29T05:01:00Z"


def test_inherit_coords_is_deterministic():
    edges = pd.DataFrame({"_src": [1, 1, 2], "_dst": [11, 10, 12]})
    coords = {10: (1.0, 1.0), 11: (2.0, 2.0)}
    assert inherit_coords(edges, coords) == {1: (1.0, 1.0)}


def test_centroid_coords_mean():
    edges = pd.DataFrame({"_src": [10, 11, 12], "_dst": [1, 1, 2]})
    coords = {10: (0.0, 0.0), 11: (2.0, 4.0)}
    assert centroid_coords(edges, coords, "_src", "_dst") == {1: (1.0, 2.0)}
    assert centroid_coords(edges.iloc[2:], coords, "_src", "_dst") == {}


# ---------------------------------------------------------------- doc blocks

def test_splice_block_replaces_only_marked_region():
    text = "a\n<!-- X:START -->\nold\n<!-- X:END -->\nb"
    assert splice_block(text, "X", "new") == "a\n<!-- X:START -->\nnew\n<!-- X:END -->\nb"
    with pytest.raises(ValueError):
        splice_block("no markers", "X", "new")
