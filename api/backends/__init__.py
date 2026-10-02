"""Backend selection: OPSMAP_BACKEND=mock (fixtures) or turingdb (live graph)."""

from __future__ import annotations

from api.backends.base import Backend
from api.config import Settings


def create_backend(settings: Settings) -> Backend:
    if settings.backend == "turingdb":
        from api.backends.turing import TuringBackend

        return TuringBackend(settings.turingdb_host, settings.turingdb_graph)
    from api.backends.mock import MockBackend

    return MockBackend(settings.fixtures_dir)
