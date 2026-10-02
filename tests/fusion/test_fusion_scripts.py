"""Pure parts of the CLI scripts: row diff, per-site summary, results markdown, post-load verification."""

import pandas as pd
import pytest

from build_theatre import EXPECTED_TYPES, verify
from graph_model import GraphBuilder
from theatre_queries import EXAMPLES, Measured, results_markdown
from versioning_demo import Snapshot, diff_rows, site_summary


def test_diff_rows_is_a_multiset_diff():
    main = pd.DataFrame({"site": ["S1", "S1", "S2"], "plant": ["A", "A", "B"]})
    branch = pd.DataFrame({"site": ["S1", "S2", "S3"], "plant": ["A", "B", "C"]})
    diff = diff_rows(main, branch)
    assert sorted(map(tuple, diff[["site", "plant", "side"]].values.tolist())) == [
        ("S1", "A", "main_only"), ("S3", "C", "branch_only")]


def test_site_summary_counts_feeds_capacity_and_rows():
    feeds_main = pd.DataFrame({"site": ["S1", "S1"], "plant": ["A", "B"], "mw": [100.0, 50.0]})
    cascade = pd.DataFrame({"site": ["S1", "S1", "S1"], "plant": ["A", "A", "B"]})
    main = Snapshot(cascade, feeds_main, 1.0, 10, 10)
    branch = Snapshot(cascade[cascade.plant == "B"], feeds_main[feeds_main.plant == "B"], 1.0, 9, 8)
    row = site_summary(main, branch).iloc[0]
    assert (row.feeds_main, row.mw_main, row.cascade_rows_main) == (2, 150.0, 3)
    assert (row.feeds_branch, row.mw_branch, row.cascade_rows_branch) == (1, 50.0, 1)


def test_examples_are_linear_and_cross_three_datasets():
    assert len(EXAMPLES) == 8
    for ex in EXAMPLES:
        assert len(set(ex.datasets)) >= 3
        match = ex.cypher.split("WHERE")[0].split("RETURN")[0]
        assert "), (" not in match, f"{ex.qid} uses a comma join (broken in turingdb 1.37)"
    hops = EXAMPLES[0].cypher.split("RETURN")[0].count("]-")
    assert hops >= 6


def test_results_markdown_lists_every_query():
    results = [Measured(ex, 3, 1.5, 0.5, "_no rows_") for ex in EXAMPLES]
    md = results_markdown(results)
    assert md.count("```cypher") == 8 and "| Q8 |" in md and "0.5" in md


class StubClient:
    """Answers the counting queries verify() issues from a fixed table."""

    def __init__(self, counts: dict[str, int], types: dict[str, str]):
        self.counts, self.types = counts, types

    def query(self, cypher: str) -> pd.DataFrame:
        if cypher.startswith("CALL db.propertyTypes()"):
            return pd.DataFrame({"propertyType": list(self.types), "valueType": list(self.types.values())})
        name = cypher.split(":")[1].split(")")[0].split("]")[0]
        return pd.DataFrame({"count": [self.counts.get(name, 0)]})


def _builder() -> GraphBuilder:
    b = GraphBuilder()
    a, c = b.add_node(("Site",), {}), b.add_node(("PowerPlant",), {})
    b.add_edge(a, c, "POWERED_BY")
    return b


def test_verify_passes_when_counts_and_types_match():
    verify(StubClient({"Site": 1, "PowerPlant": 1, "POWERED_BY": 1}, EXPECTED_TYPES), _builder())


def test_verify_reports_mismatches():
    bad_types = EXPECTED_TYPES | {"lead_time_days": "Int64"}
    with pytest.raises(RuntimeError, match="node Site: 0 != 1") as err:
        verify(StubClient({"PowerPlant": 1, "POWERED_BY": 2}, bad_types), _builder())
    assert "edge POWERED_BY: 2 != 1" in str(err.value) and "type lead_time_days" in str(err.value)
