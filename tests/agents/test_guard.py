"""The Cypher guard protects TuringDB 1.37 from runaway / write queries. No server needed."""

from __future__ import annotations

import pytest

from agents.guard import DEFAULT_LIMIT, MAX_LIMIT, UnsafeQuery, check_read_query


def test_adds_default_limit():
    out = check_read_query("MATCH (n:Site) RETURN n")
    assert out == f"MATCH (n:Site) RETURN n LIMIT {DEFAULT_LIMIT}"


def test_caps_large_limit():
    out = check_read_query(f"MATCH (n:Site) RETURN n LIMIT {MAX_LIMIT + 5000}")
    assert out.endswith(f"LIMIT {MAX_LIMIT}")


def test_keeps_small_limit():
    assert check_read_query("MATCH (n:Site) RETURN n LIMIT 5").endswith("LIMIT 5")


def test_count_aggregate_needs_no_limit():
    out = check_read_query("MATCH (n:Site) RETURN count(n) AS c")
    assert "LIMIT" not in out


@pytest.mark.parametrize("cypher", [
    "MATCH (n:Site) DELETE n",
    "MATCH (n:Site) SET n.x = 1",
    "CREATE (:Site)",
    "MATCH (n) REMOVE n.x",
    "CHANGE DELETE",
])
def test_rejects_writes(cypher):
    with pytest.raises(UnsafeQuery):
        check_read_query(cypher)


@pytest.mark.parametrize("cypher", [
    "MATCH (a:Site), (b:Supplier) RETURN a, b",  # comma join hangs 1.37
    "MATCH (a:Site)-[:R*1..3]->(b) RETURN a",     # var-length
    "MATCH (n:Site) RETURN n UNION MATCH (m) RETURN m",
    "MATCH (n) WHERE n.x IN [1,2] RETURN n",
    "MATCH (n) OPTIONAL MATCH (n)-[:R]->(m) RETURN n",
    "MATCH (n) WITH n RETURN n",
    "MATCH (n) RETURN collect(n)",
])
def test_rejects_unsupported_or_dangerous(cypher):
    with pytest.raises(UnsafeQuery):
        check_read_query(cypher)


def test_allows_linear_path_and_db_calls():
    ok = "MATCH (s:Site)-[:POWERED_BY]->(p:PowerPlant) WHERE s.site_id = 'SITE01' RETURN p"
    assert check_read_query(ok).startswith("MATCH (s:Site)")
    assert check_read_query("CALL db.labels()") == "CALL db.labels()"


def test_blocks_other_procedures():
    with pytest.raises(UnsafeQuery):
        check_read_query("CALL db.history()")


def test_string_literal_with_keyword_is_not_a_write():
    # 'DELETE' inside a string must not trip the write check
    out = check_read_query("MATCH (n:Report) WHERE n.text = 'we will DELETE nothing' RETURN n")
    assert out.endswith(f"LIMIT {DEFAULT_LIMIT}")


def test_marker_spec_survives_the_string_literal_round_trip():
    """Specs are written with string_literal (quotes swapped) and read back from TuringDB on restart."""
    import json

    from agents.branches import parse_marker_spec
    from api.backends.turing_session import string_literal

    spec = {"actions": [{"action": "wipe_bbox", "args": {"west": -2.39, "labels": None}}], "parent": "main",
            "note": "Manchester's port"}
    stored = string_literal(json.dumps(spec, sort_keys=True))[1:-1]  # what the marker property holds
    assert '"' not in stored
    assert parse_marker_spec(stored) == spec
