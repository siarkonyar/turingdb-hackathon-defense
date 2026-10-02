"""Backend-agnostic errors and timing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from api.models import QueryTrace


class ApiError(Exception):
    status_code = 500


class NotFound(ApiError):
    status_code = 404


class Conflict(ApiError):
    status_code = 409


class BackendUnavailable(ApiError):
    status_code = 503


@dataclass
class Stopwatch:
    """Collects per-query server timings for one API call; `timed()` fills the Timed fields."""

    engine: str
    started: float = field(default_factory=time.perf_counter)
    traces: list[QueryTrace] = field(default_factory=list)

    def record(self, cypher: str, ms: float | None) -> None:
        self.traces.append(QueryTrace(cypher=cypher, ms=None if ms is None else round(ms, 3)))

    def timed(self) -> dict[str, Any]:
        roundtrip = (time.perf_counter() - self.started) * 1000
        server = sum(t.ms or 0.0 for t in self.traces)
        latency = server if self.engine == "turingdb" else roundtrip
        return {"engine": self.engine, "latency_ms": round(latency, 3), "roundtrip_ms": round(roundtrip, 3),
                "queries": list(self.traces)}
