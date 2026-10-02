"""A tiny hand-built fixture in the mock format, so API tests run without TuringDB or the 1.7 MB fixture.

    plant P1 --powers--> site S1 <--patrols-- drone D1
    plant P2 --powers--> site S1           (S1 has two feeds)
    supplier U1 <--supplied_by-- part X1 --delivered_to--> site S2
    report R1 (batch 1) mentions P1;  report R2 (batch 2) mentions U1 and contradicts R1
    hypothesis 1 removes U1
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.backends.mock import MockBackend
from api.main import create_app


def _node(nid, label, **props):
    return {"id": nid, "label": label, "props": {"name": nid, **props}}


FIXTURE = {
    "meta": {},
    "nodes": [
        _node("P1", "PowerPlant", latitude=53.0, longitude=-2.0, capacity_mw=800.0, primary_fuel="Gas"),
        _node("P2", "PowerPlant", latitude=53.1, longitude=-2.1, capacity_mw=20.0, primary_fuel="Solar"),
        _node("S1", "Site", latitude=53.05, longitude=-2.05, exposure=3000),
        _node("S2", "Site", latitude=48.0, longitude=2.0),
        _node("U1", "Supplier", latitude=45.0, longitude=7.0),
        _node("X1", "Part"),
        _node("D1", "Drone", latitude=53.06, longitude=-2.06),
        _node("C1", "Crime", latitude=53.04, longitude=-2.04, timestamp="2017-08-01T00:00:00Z"),
        _node("R1", "Report", latitude=53.0, longitude=-2.0, batch=1, report_id="R1", text="plant hit",
              timestamp="2026-09-29T06:00:00Z", confidence=0.7, claim="damaged", source_type="drone"),
        _node("R2", "Report", latitude=45.0, longitude=7.0, batch=2, report_id="R2", text="supplier down",
              timestamp="2026-09-29T08:00:00Z", confidence=0.4, claim="disrupted", source_type="SIGINT"),
    ],
    "edges": [
        ["S1", "P1", "POWERED_BY", {"distance_km": 4.0}],
        ["S1", "P2", "POWERED_BY", {"distance_km": 9.0}],
        ["D1", "S1", "PATROLS", {}],
        ["X1", "U1", "SUPPLIED_BY", {}],
        ["X1", "S2", "DELIVERED_TO", {}],
        ["C1", "S1", "NEAR", {"distance_km": 1.0}],
        ["R1", "P1", "MENTIONS", {}],
        ["R2", "U1", "MENTIONS", {}],
        ["R2", "R1", "CONTRADICTS", {}],
    ],
    "commits": [
        {"hash": "aaaa000000000000", "index": 0, "node_delta": 8, "edge_delta": 6},
        {"hash": "bbbb000000000000", "index": 1, "node_delta": 1, "edge_delta": 1},
        {"hash": "cccc000000000000", "index": 2, "node_delta": 1, "edge_delta": 2},
    ],
    "hypotheses": [{"id": "1", "label": "H1", "confidence": 0.6, "strike": ["U1"], "description": "supplier lost"}],
    "tracks": [{"id": "D1", "name": "D1", "path": [[-2.06, 53.06], [-2.05, 53.07]], "timestamps": [100, 200]}],
}


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    with gzip.open(tmp_path / "theatre_mock.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(FIXTURE, fh)
    return tmp_path


@pytest.fixture
def backend(fixtures_dir: Path) -> MockBackend:
    return MockBackend(fixtures_dir)


@pytest.fixture
def client(backend: MockBackend):
    with TestClient(create_app(backend)) as c:
        yield c
