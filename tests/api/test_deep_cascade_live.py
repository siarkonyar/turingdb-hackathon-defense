"""Impact cascade against the live `theatre` graph. Read-only: asserts that no change is created.
Skipped when the server or graph is unavailable."""

from __future__ import annotations

import os

import pytest

from api.backends.turing import ENGINE, TuringBackend
from api.refs import Ref
from api.support import Stopwatch

HOST = os.environ.get("TURINGDB_HOST", "http://localhost:6666")
GRAPH = os.environ.get("TURINGDB_GRAPH", "theatre")
REACH_BUDGET_MS = 500  # Hormuz measured at ~8 ms engine time; generous for a laptop under load


def _reachable() -> bool:
    try:
        from turingdb import TuringDB

        return GRAPH in TuringDB(host=HOST).list_available_graphs()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason=f"TuringDB {HOST} with graph {GRAPH} not available")


@pytest.fixture(scope="module")
def engine():
    from api.deep_cascade_live import DeepCascade

    return DeepCascade(TuringBackend(HOST, GRAPH))


def origin_id(engine, name: str) -> str:
    s = engine.session(Ref("main"))
    return next(n.id for n, _ in engine.catalog(s) if n.name == name)


def change_count(engine) -> int:
    return len(engine.session(Ref("main")).q("CHANGE LIST"))


def test_catalog_lists_all_chokepoints_ports_and_facilities(engine):
    kinds = [k for _, k in engine.catalog(engine.session(Ref("main")))]
    assert kinds.count("chokepoint") == 15 and kinds.count("port") == 71 and kinds.count("facility") > 4000


def test_hormuz_cascade_is_staged_weighted_and_fast(engine):
    before = change_count(engine)
    r = engine.compute(Ref("main"), origin_id(engine, "Strait of Hormuz"))
    assert r.origin.kind == "chokepoint" and r.origin.status == "lost" and r.origin_kind == "chokepoint"
    # 8 facilities ship through Hormuz; FAC00374 loses only 2.4% (< MIN_SEVERITY), so 7 are degree 1
    assert r.stages[0].count == 7 and r.stages[0].hits[0].via == "TRANSITED"
    assert r.max_degree == len(r.stages) >= 5 and r.graph_hops == r.max_degree + 1
    assert [st.degree for st in r.stages] == list(range(1, r.max_degree + 1))
    assert r.total_affected == sum(st.count for st in r.stages)
    assert r.reach.reached >= r.total_affected - r.stages[0].count
    assert r.reach.ms is not None and r.reach.ms < REACH_BUDGET_MS
    assert "{1,12}" in r.reach.cypher
    assert r.engine == ENGINE and r.queries
    assert change_count(engine) == before  # read-only


def test_every_hit_has_a_parent_in_the_previous_degree_and_matching_arc(engine):
    r = engine.compute(Ref("main"), origin_id(engine, "Strait of Hormuz"))
    previous = {r.origin.id}
    for stage in r.stages:
        ids = {h.node.id for h in stage.hits}
        assert all(h.parent_id in previous for h in stage.hits)
        assert all(0.05 <= h.severity <= 1 for h in stage.hits)
        assert all(a.hop == stage.degree and a.target_id in ids for a in stage.arcs)
        assert all(h.node.status == "at_risk" and h.node.lat is not None for h in stage.hits)
        previous = ids


def test_facility_origin_starts_at_its_buyers(engine):
    s = engine.session(Ref("main"))
    network, index = engine.network(s), engine.facility_index(s)
    fid = max(network.out_edges, key=lambda f: len(network.out_edges[f]))
    origin = index.by_fid[fid]
    r = engine.compute(Ref("main"), origin.id)
    assert r.origin_kind == "facility" and r.graph_hops == r.max_degree
    assert origin.id not in {h.node.id for st in r.stages for h in st.hits}
    assert all(h.parent_id == origin.id for h in r.stages[0].hits)


def test_port_origin_uses_loaded_at(engine):
    r = engine.compute(Ref("main"), origin_id(engine, "Port of Busan"))
    assert r.origin_kind == "port" and r.stages and r.stages[0].hits[0].via == "LOADED_AT"


def test_seeds_by_origin_matches_single_origin_seeds(engine):
    s = engine.session(Ref("main"))
    hormuz = engine.origin(s, origin_id(engine, "Strait of Hormuz"))
    single = engine.seeds(s, hormuz)
    grouped = engine.seeds_by_origin(s, "chokepoint")
    assert dict(grouped[hormuz.node.id].severities) == pytest.approx(dict(single.severities))
    assert len(grouped) <= 15


def test_non_origin_label_is_rejected(engine):
    s = engine.session(Ref("main"))
    plant = s.q("MATCH (n:PowerPlant) RETURN n LIMIT 1")["n"].iloc[0]
    with pytest.raises(ValueError):
        engine.compute(Ref("main"), str(plant))


def test_session_records_timing(engine):
    sw = Stopwatch(ENGINE)
    engine.session(Ref("main"), sw).q("MATCH (k:Chokepoint) RETURN count(k)")
    assert sw.traces and sw.traces[0].ms is not None
