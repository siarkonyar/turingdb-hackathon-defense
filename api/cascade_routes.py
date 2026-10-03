"""OpsMap routes for the deep-supply impact cascade (read-only; never creates a branch).

    GET  /cascade/origins?q=     place search (chokepoints, ports, facilities), English place-name aliases
    POST /cascade                {origin_id, branch, min_severity} -> per-degree CascadeResponse
    POST /cascade/ask            {question, branch, min_severity} -> same, or 422 {detail, candidates}

Mounted only on the live TuringDB backend. Contract: docs/api.md "Impact cascade".
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, Sequence

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from api.cascade_resolve import pick, resolve
from api.models import CascadeAskRequest, CascadeRequest, CascadeResponse, Node, OriginKind, OriginsResponse
from api.refs import Ref, parse_ref

log = logging.getLogger("opsmap.cascade")
MAX_CANDIDATES = 8


class CascadeEngine(Protocol):
    def session(self, ref: Ref, sw: Any = None) -> Any: ...
    def catalog(self, s: Any) -> Sequence[tuple[Node, OriginKind]]: ...
    def compute(self, ref: Ref, origin_id: str, min_severity: float = ...) -> CascadeResponse: ...


def _default_engine(app: FastAPI) -> CascadeEngine:
    from api.deep_cascade_live import DeepCascade

    return DeepCascade(app.state.backend)


def register_cascade_routes(app: FastAPI,
                            engine_factory: Callable[[FastAPI], CascadeEngine] | None = None) -> None:
    holder: dict[str, CascadeEngine] = {}

    def engine() -> CascadeEngine:
        if "engine" not in holder:
            holder["engine"] = (engine_factory or _default_engine)(app)
        return holder["engine"]

    def catalog(branch: str) -> Sequence[tuple[Node, OriginKind]]:
        eng = engine()
        return eng.catalog(eng.session(parse_ref(branch)))

    @app.get("/cascade/origins", response_model=OriginsResponse, response_model_exclude_none=True)
    def origins(q: str = Query(min_length=2, max_length=120), branch: str = "main"):
        return OriginsResponse(query=q, candidates=resolve(q, catalog(branch), MAX_CANDIDATES))

    @app.post("/cascade", response_model=CascadeResponse, response_model_exclude_none=True)
    def cascade(req: CascadeRequest):
        return engine().compute(parse_ref(req.branch), req.origin_id, req.min_severity)

    @app.post("/cascade/ask", response_model=CascadeResponse, response_model_exclude_none=True)
    def ask(req: CascadeAskRequest):
        candidates = resolve(req.question, catalog(req.branch), MAX_CANDIDATES)
        chosen = pick(candidates)
        if chosen is None:
            detail = ("No chokepoint, port or facility recognised in the question" if not candidates
                      else "Several places match: choose one")
            return JSONResponse(status_code=422, content={
                "detail": detail,
                "candidates": [c.model_dump(mode="json", exclude_none=True) for c in candidates],
            })
        log.info("cascade ask %r -> %s", req.question, chosen.node.name)
        return engine().compute(parse_ref(req.branch), chosen.node.id, req.min_severity)
