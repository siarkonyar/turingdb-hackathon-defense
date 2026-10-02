"""Integration checks against a running server with `theatre` built; skipped otherwise."""

import pytest

from config import SERVER_URL

turingdb = pytest.importorskip("turingdb")


@pytest.fixture(scope="module")
def client():
    try:
        c = turingdb.TuringDB(host=SERVER_URL)
        if "theatre" not in c.list_available_graphs():
            pytest.skip("theatre graph not built")
        c.load_graph("theatre", raise_if_loaded=False)
        c.set_graph("theatre")
        c.checkout()
        return c
    except Exception as exc:  # connection refused, server errors
        pytest.skip(f"TuringDB not usable: {exc}")


def _count(c, q: str) -> int:
    return int(c.query(q).iloc[0, 0])


def test_history_has_base_plus_report_batches(client):
    assert len(client.query("CALL db.history()")) == 5  # empty root, base load, 3 report batches


def test_every_site_and_part_supplier_is_powered_and_located(client):
    assert _count(client, "MATCH (s:Site)-[:POWERED_BY]->(p:PowerPlant) RETURN count(p)") == 18
    assert _count(client, "MATCH (s:Site)-[:LOCATED_IN]->(c:Country) RETURN count(c)") == 6
    assert _count(client, "MATCH (s:Supplier {source:'supply_chain'})-[:LOCATED_IN]->(c:Country) "
                          "RETURN count(c)") == 40


def test_country_merge_and_synthetic_flags(client):
    assert _count(client, "MATCH (c:Country) RETURN count(c)") == 168
    assert _count(client, "MATCH (c:Country {country_code:'GBR'}) RETURN count(c)") == 1
    assert _count(client, "MATCH (a)-[e:POWERED_BY]->(b) WHERE e.synthetic = true RETURN count(e)") == \
        _count(client, "MATCH (a)-[e:POWERED_BY]->(b) RETURN count(e)")


def test_reports_and_contradictions(client):
    assert _count(client, "MATCH (r:Report) RETURN count(r)") == 21
    assert _count(client, "MATCH (a:Report)-[e:CONTRADICTS]->(b:Report) RETURN count(e)") == 6
