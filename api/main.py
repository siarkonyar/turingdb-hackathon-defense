"""OpsMap API: the operational-picture contract over TuringDB (or mock fixtures).

    uv run uvicorn api.main:app --reload                         # mock fixtures (default)
    OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app          # live `theatre` graph

Contract: docs/api.md. Shapes: api/models.py.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from api.backends import create_backend
from api.backends.base import NODE_KINDS, Backend
from api.config import load_settings
from api.models import (BranchesResponse, DiffResponse, MetaResponse, NeighboursResponse, NodesResponse,
                        ReportsResponse, SimulateRequest, SimulateResponse, TracksResponse)
from api.refs import parse_bbox, parse_kinds, parse_ref
from api.support import ApiError

log = logging.getLogger("opsmap.api")
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 5  # level 9 costs ~3x the CPU for ~2% smaller payloads


def raw_json(model: BaseModel) -> Response:
    """Serialise in pydantic-core directly (skips FastAPI's re-validation of 35k-node payloads).
    Null fields are omitted, so clients treat every optional Node field as possibly absent."""
    return Response(content=model.model_dump_json(exclude_none=True), media_type="application/json")


def parse_until(raw: str | None) -> str | None:
    """Normalise an ISO-8601 instant to the graph's `YYYY-MM-DDTHH:MM:SSZ` form (UTC)."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"until must be ISO-8601, got {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(backend: Backend | None = None) -> FastAPI:
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.backend = backend or create_backend(settings)
        log.info("OpsMap API using %s backend", app.state.backend.meta().engine)
        yield

    app = FastAPI(title="OpsMap API", version="1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("backend error: %s", exc)
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def bad_input(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def get_backend(request: Request) -> Backend:
        return request.app.state.backend

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/meta", response_model=MetaResponse)
    def meta(b: Backend = Depends(get_backend)):
        return b.meta()

    @app.get("/nodes", response_model=NodesResponse)
    def nodes(bbox: str | None = None, types: str | None = None, branch: str = "main",
              b: Backend = Depends(get_backend)):
        return raw_json(b.nodes(parse_ref(branch), parse_kinds(types, NODE_KINDS), parse_bbox(bbox)))

    @app.get("/node/{node_id}/neighbours", response_model=NeighboursResponse)
    def neighbours(node_id: str, branch: str = "main", b: Backend = Depends(get_backend)):
        return b.neighbours(node_id, parse_ref(branch))

    @app.post("/simulate", response_model=SimulateResponse)
    def simulate(req: SimulateRequest, b: Backend = Depends(get_backend)):
        return b.simulate(req.node_id, parse_ref(req.base_branch))

    @app.get("/diff", response_model=DiffResponse)
    def diff(a: str = Query(...), b_ref: str = Query(..., alias="b"), b: Backend = Depends(get_backend)):
        return raw_json(b.diff(parse_ref(a), parse_ref(b_ref)))

    @app.get("/branches", response_model=BranchesResponse)
    def branches(b: Backend = Depends(get_backend)):
        return b.branches()

    @app.delete("/branches/{branch_id}", status_code=204)
    def discard(branch_id: str, b: Backend = Depends(get_backend)) -> Response:
        b.discard(parse_ref(branch_id).branch)
        return Response(status_code=204)

    @app.get("/reports", response_model=ReportsResponse)
    def reports(until: str | None = None, branch: str = "main", b: Backend = Depends(get_backend)):
        return b.reports(parse_ref(branch), parse_until(until))

    @app.get("/tracks", response_model=TracksResponse)
    def tracks(branch: str = "main", b: Backend = Depends(get_backend)):
        return b.tracks(parse_ref(branch))

    return app


app = create_app()
