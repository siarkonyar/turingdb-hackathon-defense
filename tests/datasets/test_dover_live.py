"""Read-only integration checks on the dedicated Dover graph; never call an LLM."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("DOVER_LIVE") != "1", reason="set DOVER_LIVE=1 for port 6667")


def test_live_graph_and_cascade():
    from api.backends.turing import TuringBackend
    from api.deep_cascade_live import DeepCascade
    from api.refs import Ref
    from api.support import Stopwatch
    from datasets.dover.build import HOST
    from datasets.dover.model import SOURCE, build_corridor

    backend = TuringBackend(HOST, "dover")
    assert backend.meta().graph == "dover"
    s = backend.session(Ref("main"), Stopwatch("turingdb"))
    head = s.head()
    baseline = int(s.q("MATCH (n) RETURN count(n)").iloc[0, 0])
    assert baseline == 6095
    assert s.q("MATCH (n) RETURN DISTINCT n.source AS source")["source"].tolist() == [SOURCE]
    fingerprint = s.q("MATCH (n:Dataset) RETURN n.build_fingerprint AS fingerprint").iloc[0, 0]
    expected = build_corridor()
    assert fingerprint == expected.graph.nodes[expected.ids["dataset:dover"]].props["build_fingerprint"]
    assert len(backend.nodes(Ref("main"), ("facility",), None).nodes) == 1252
    oid = str(s.q("MATCH (n:Chokepoint) RETURN n").iloc[0, 0])
    result = DeepCascade(backend).compute(Ref("main"), oid)
    assert result.connected and result.max_degree == 12 and result.total_affected == 778
    assert len(result.platforms) == 78
    assert s.head() == head
    assert int(s.q("MATCH (n) RETURN count(n)").iloc[0, 0]) == baseline


def test_live_dependency_and_recovery_queries():
    from turingdb import TuringDB
    from datasets.dover.build import HOST

    c = TuringDB(host=HOST)
    c.set_graph("dover")
    f = c.query("MATCH (o:Chokepoint {entity_id: 'chokepoint:dover'})<-[:DEPENDS_ON]-{1,16}(n) "
                "RETURN DISTINCT n.entity_id AS entity LIMIT 2000")
    assert "capability:paris:military_hospital" in f["entity"].tolist()
    f = c.query("MATCH (f:Facility {entity_id: 'mission:ashford:military_hospital'})"
                "-[:HAS_RECOVERY]->(r:RecoveryOption)-[:REQUIRES]->(p) "
                "RETURN r.recovery_kind AS kind, p.entity_id AS provider LIMIT 50")
    assert "relocate_service" in f["kind"].tolist()
    assert any(p.startswith("mission:") for p in f.loc[f["kind"] == "relocate_service", "provider"])


def test_dover_api_mounts_cascade_without_original_agents(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import create_app

    monkeypatch.setenv("OPSMAP_BACKEND", "turingdb")
    monkeypatch.setenv("TURINGDB_GRAPH", "dover")
    monkeypatch.setenv("TURINGDB_HOST", "http://localhost:6667")
    with TestClient(create_app()) as client:
        assert client.get("/meta").json()["graph"] == "dover"
        assert client.get("/agent/status").status_code == 404
        response = client.get("/nodes", params={"types": "facility,port,chokepoint,plant"})
        assert response.status_code == 200
        assert len(response.json()["nodes"]) == 1284
        assert client.get("/cascade/origins", params={"q": "Dover Strait"}).status_code == 200
