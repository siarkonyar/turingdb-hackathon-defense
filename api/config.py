"""Runtime configuration, read once from the environment.

    OPSMAP_BACKEND   mock (default) | turingdb   -- the single switch between fixtures and the live graph
    TURINGDB_HOST    http://localhost:6666
    TURINGDB_GRAPH   theatre
    OPSMAP_CORS      comma-separated origins allowed to call the API (default: the Vite dev server)
    OPSMAP_FIXTURES  directory holding the mock fixtures (default: api/mock/fixtures)

Any of these may also come from a gitignored `.env` file at the repo root (see .env.example); real
environment variables win over it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from api.env import load_env

API_DIR = Path(__file__).resolve().parent
MOCK_FIXTURES_DIR = API_DIR / "mock" / "fixtures"

BACKENDS = ("mock", "turingdb")
DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"


@dataclass(frozen=True)
class Settings:
    backend: str
    turingdb_host: str
    turingdb_graph: str
    cors_origins: tuple[str, ...]
    fixtures_dir: Path


def load_settings() -> Settings:
    load_env()
    backend = os.environ.get("OPSMAP_BACKEND", "mock").strip().lower()
    if backend not in BACKENDS:
        raise ValueError(f"OPSMAP_BACKEND must be one of {BACKENDS}, got {backend!r}")
    origins = tuple(o.strip() for o in os.environ.get("OPSMAP_CORS", DEFAULT_CORS).split(",") if o.strip())
    return Settings(
        backend=backend,
        turingdb_host=os.environ.get("TURINGDB_HOST", "http://localhost:6666"),
        turingdb_graph=os.environ.get("TURINGDB_GRAPH", "theatre"),
        cors_origins=origins,
        fixtures_dir=Path(os.environ.get("OPSMAP_FIXTURES", MOCK_FIXTURES_DIR)),
    )
