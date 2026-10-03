"""Integration tests against a running TuringDB server with the `theatre` graph.
Skipped when the server or graph is unavailable. Every strike branch created here is discarded."""

from __future__ import annotations

import os

import pytest

from api.backends.turing import TuringBackend
from api.refs import Ref
from api.support import Conflict, NotFound

HOST = os.environ.get("TURINGDB_HOST", "http://localhost:6666")
GRAPH = os.environ.get("TURINGDB_GRAPH", "theatre")


def _reachable() -> bool:
    try:
        from turingdb import TuringDB

        return GRAPH in TuringDB(host=HOST).list_available_graphs()
    except Exception:  # server down or SDK missing: the whole module is skipped
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason=f"TuringDB {HOST} with graph {GRAPH} not available")


@pytest.fixture(scope="module")
def live() -> TuringBackend:
    return TuringBackend(HOST, GRAPH)


@pytest.fixture
def feed_plant(live: TuringBackend) -> str:
    """A plant that powers a Site, found through the API itself."""
    site = live.nodes(Ref("main"), ("site",), None).nodes[0]
    groups = live.neighbours(site.id, Ref("main")).groups
    return next(g for g in groups if g.rel == "POWERED_BY" and g.direction == "out").nodes[0].id


def test_nodes_and_branches_are_served_with_server_latency(live: TuringBackend):
    sites = live.nodes(Ref("main"), ("site",), None)
    assert sites.engine == "turingdb" and sites.nodes and all(n.lat is not None for n in sites.nodes)
    main = live.branches().branches[0]
    assert main.id == "main" and main.commits


def test_strike_creates_change_cascades_and_discards(live: TuringBackend, feed_plant: str):
    result = live.simulate(feed_plant, Ref("main"))
    try:
        assert result.struck.id == feed_plant and result.struck.status == "lost"
        assert any(a.node.kind == "site" and a.via == "POWERED_BY" for a in result.affected)
        assert result.arcs and result.kpis.assets_at_risk >= 1
        assert any(q.cypher.startswith("MATCH (x)<-[:POWERED_BY]") for q in result.queries)
        diff = live.diff(Ref("main"), Ref(result.branch))
        assert [n.id for n in diff.removed] == [feed_plant]
        located = {a.node.id for a in result.affected if a.node.kind in ("site", "supplier", "drone")}
        assert located <= {c.node.id for c in diff.changed}
        assert feed_plant in {n.id for n in live.nodes(Ref("main"), ("plant",), None).nodes}  # main untouched
    finally:
        live.discard(result.branch)
    with pytest.raises(NotFound):
        live.nodes(Ref(result.branch), ("site",), None)


def test_reports_tracks_neighbours_and_history(live: TuringBackend, feed_plant: str):
    reports = live.reports(Ref("main"), None).reports
    assert reports == sorted(reports, key=lambda r: r.node.timestamp or "")
    if reports:
        cutoff = reports[0].node.timestamp
        assert all(r.node.timestamp <= cutoff for r in live.reports(Ref("main"), cutoff).reports)
    for track in live.tracks(Ref("main")).tracks:
        assert len(track.path) == len(track.timestamps) and track.timestamps == sorted(track.timestamps)
    hood = live.neighbours(feed_plant, Ref("main"))
    assert hood.node.kind == "plant" and hood.properties.get("name") == hood.node.name
    assert any(g.rel == "POWERED_BY" and g.direction == "in" for g in hood.groups)
    commits = live.branches().branches[0].commits
    assert [c.index for c in commits] == list(range(len(commits)))
    first, last = commits[0].hash, commits[-1].hash
    assert live.diff(Ref("main", first), Ref("main", last)).engine == "turingdb"


def test_invalid_ids_never_reach_cypher(live: TuringBackend):
    with pytest.raises(NotFound):
        live.neighbours("1 OR 1=1", Ref("main"))
    with pytest.raises(NotFound):
        live.simulate("abc", Ref("main"))


def test_unknown_branch_cannot_be_discarded(live: TuringBackend):
    with pytest.raises((NotFound, Conflict)):
        live.discard("999999")


def test_deep_facilities_and_ports_are_served_and_strikable(live: TuringBackend):
    facilities = live.nodes(Ref("main"), ("facility",), None).nodes
    ports = live.nodes(Ref("main"), ("port",), None).nodes
    assert len(facilities) == 4404 and len(ports) == 71
    assert all(n.lat is not None and n.kind == "facility" for n in facilities)
    # a facility that supplies others: its buyers are put at risk through SUPPLIES
    struck = None
    for node in facilities[:300]:
        result = live.simulate(node.id, Ref("main"))
        if any(a.via == "SUPPLIES" for a in result.affected):
            struck = result
            break
        live.discard(result.branch)
    assert struck is not None, "no facility in the sample cascades to a buyer"
    try:
        assert struck.struck.status == "lost" and struck.arcs
        diff = live.diff(Ref("main"), Ref(struck.branch))
        assert [n.kind for n in diff.removed] == ["facility"]
    finally:
        live.discard(struck.branch)
