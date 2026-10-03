"""/cascade routes with a fake engine (no TuringDB). The live engine is covered by test_deep_cascade_live.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.cascade_routes import register_cascade_routes
from api.main import create_app
from api.models import CascadeResponse, ReachProbe
from api.nodes import make_node, with_status
from api.support import NotFound

HORMUZ = make_node(11, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4})
BUSAN = make_node(12, "Port", {"name": "Port of Busan", "latitude": 35.1, "longitude": 129.0})
HAMBURG = make_node(13, "Port", {"name": "Port of Hamburg", "latitude": 53.5, "longitude": 9.9})


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def session(self, ref, sw=None):
        return ref

    def catalog(self, s):
        return [(HORMUZ, "chokepoint"), (BUSAN, "port"), (HAMBURG, "port")]

    def compute(self, ref, origin_id, min_severity=0.05):
        self.calls.append((str(ref), origin_id, min_severity))
        if origin_id == "404":
            raise NotFound("node 404 not on main")
        return CascadeResponse(engine="turingdb", latency_ms=1.0, roundtrip_ms=2.0, branch=str(ref),
                               origin=with_status(HORMUZ, "lost"), origin_kind="chokepoint", min_severity=min_severity,
                               stages=[], max_degree=0, graph_hops=0, total_affected=0,
                               reach=ReachProbe(cypher="MATCH ...", depth_limit=12, reached=0, ms=1.0), platforms=[])


@pytest.fixture
def fake() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def cclient(backend, fake):
    app = create_app(backend)
    register_cascade_routes(app, engine_factory=lambda _app: fake)
    with TestClient(app) as c:
        yield c


def test_routes_absent_on_mock_backend_without_registration(client):
    assert client.post("/cascade", json={"origin_id": "1"}).status_code == 404


def test_origins_lists_ranked_candidates(cclient):
    body = cclient.get("/cascade/origins", params={"q": "hormuz"}).json()
    assert body["query"] == "hormuz" and body["candidates"][0]["node"]["name"] == "Strait of Hormuz"
    assert body["candidates"][0]["origin_kind"] == "chokepoint"


def test_origins_rejects_too_short_query(cclient):
    assert cclient.get("/cascade/origins", params={"q": "h"}).status_code == 422


def test_cascade_by_id_passes_branch_and_threshold(cclient, fake):
    r = cclient.post("/cascade", json={"origin_id": "11", "branch": "main", "min_severity": 0.1})
    assert r.status_code == 200 and r.json()["origin"]["status"] == "lost"
    assert [(c[1], c[2]) for c in fake.calls] == [("11", 0.1)]


def test_cascade_validates_threshold(cclient):
    assert cclient.post("/cascade", json={"origin_id": "11", "min_severity": 0.9}).status_code == 422


def test_cascade_unknown_origin_is_404(cclient):
    assert cclient.post("/cascade", json={"origin_id": "404"}).status_code == 404


def test_ask_resolves_plain_english_question(cclient, fake):
    r = cclient.post("/cascade/ask", json={"question": "What happens if the Strait of Hormuz closes?"})
    assert r.status_code == 200 and fake.calls[-1][1] == "11"


def test_ask_ambiguous_is_422_with_candidates(cclient):
    r = cclient.post("/cascade/ask", json={"question": "Busan and Hamburg close"})
    body = r.json()
    assert r.status_code == 422 and len(body["candidates"]) >= 2 and "choose" in body["detail"].lower()


def test_ask_unknown_place_is_422_with_candidates(cclient):
    r = cclient.post("/cascade/ask", json={"question": "what happens tomorrow?"})
    assert r.status_code == 422 and r.json()["candidates"] == []
