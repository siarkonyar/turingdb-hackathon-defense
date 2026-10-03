"""OpsMap routes for the deep-supply impact cascade (read-only; never creates a branch).

    GET  /cascade/origins?q=     place search (chokepoints, ports, facilities, companies, countries, plants, items)
    POST /cascade                {origin_id, branch, min_severity} -> per-degree CascadeResponse
    POST /cascade/ask            {question, branch, min_severity} -> same, or 422 {detail, candidates}

/cascade/ask resolves the question deterministically first (aliases + name tokens: instant, no model). Only when
that finds no confident match does an LLM extractor (agents/place_extractor.py) name the entity, which is then
looked up the same way. Something the graph does not hold, or that has no link into the supply network, is
answered as "not connected to anything in the TuringDB graph dataset".

Mounted only on the live TuringDB backend. Contract: docs/api.md "Impact cascade".
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, Sequence

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from api.cascade_resolve import CONFIDENT, pick, resolve
from api.models import (CascadeAskRequest, CascadeRequest, CascadeResponse, Node, OriginCandidate, OriginKind,
                        OriginsResponse)
from api.refs import Ref, parse_ref

log = logging.getLogger("opsmap.cascade")
MAX_CANDIDATES = 8
HINT_KIND: dict[str, str] = {"power_plant": "plant"}  # extractor kind -> OriginKind where they differ
NOT_RECOGNISED = ("Nothing in the question is connected to anything in the TuringDB graph dataset. Name a "
                  "chokepoint, port, facility, company, country, power plant or supply item.")


class CascadeEngine(Protocol):
    def session(self, ref: Ref, sw: Any = None) -> Any: ...
    def catalog(self, s: Any) -> Sequence[tuple[Node, OriginKind]]: ...
    def compute(self, ref: Ref, origin_id: str, min_severity: float = ...) -> CascadeResponse: ...


class Mention(Protocol):
    name: str
    kind: str


Extractor = Callable[[str], Sequence[Mention]]


def _default_engine(app: FastAPI) -> CascadeEngine:
    from api.deep_cascade_live import DeepCascade

    return DeepCascade(app.state.backend)


def _pick_with_hint(candidates: Sequence[OriginCandidate], kind_hint: str) -> OriginCandidate | None:
    """pick(), or the single top-scoring candidate of the kind the extractor named when several kinds tie."""
    chosen = pick(candidates)
    if chosen is not None or not candidates or candidates[0].score < CONFIDENT:
        return chosen
    hint = HINT_KIND.get(kind_hint, kind_hint)
    top = [c for c in candidates if c.score == candidates[0].score and c.origin_kind == hint]
    return top[0] if len(top) == 1 else None


def _reject(detail: str, candidates: Sequence[OriginCandidate] = ()) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "detail": detail,
        "candidates": [c.model_dump(mode="json", exclude_none=True) for c in candidates],
    })


def _merge(groups: Sequence[Sequence[OriginCandidate]]) -> list[OriginCandidate]:
    seen: dict[str, OriginCandidate] = {}
    for group in groups:
        for c in group:
            if c.score >= CONFIDENT and (c.node.id not in seen or c.score > seen[c.node.id].score):
                seen[c.node.id] = c
    return sorted(seen.values(), key=lambda c: -c.score)[:MAX_CANDIDATES]


def register_cascade_routes(app: FastAPI,
                            engine_factory: Callable[[FastAPI], CascadeEngine] | None = None,
                            extractor_factory: Callable[[], Extractor] | None = None) -> None:
    """`extractor_factory` enables the LLM fallback in /cascade/ask; without it only the deterministic resolver runs."""
    holder: dict[str, Any] = {}

    def engine() -> CascadeEngine:
        if "engine" not in holder:
            holder["engine"] = (engine_factory or _default_engine)(app)
        return holder["engine"]

    def extractor() -> Extractor | None:
        if "extractor" not in holder:
            try:
                holder["extractor"] = extractor_factory() if extractor_factory else None
            except Exception as exc:  # e.g. no FEATHERLESS_API_KEY: the deterministic path still works
                log.warning("cascade question extractor unavailable: %s", exc)
                holder["extractor"] = None
        return holder["extractor"]

    def catalog(branch: str) -> Sequence[tuple[Node, OriginKind]]:
        eng = engine()
        s = eng.session(parse_ref(branch))
        search = getattr(eng, "search_catalog", None)  # wider catalog when the engine has one
        return search(s) if search else eng.catalog(s)

    def run(req: CascadeAskRequest, chosen: OriginCandidate, understood_as: str | None = None) -> CascadeResponse:
        log.info("cascade ask %r -> %s", req.question, chosen.node.name)
        result = engine().compute(parse_ref(req.branch), chosen.node.id, req.min_severity)
        return result.model_copy(update={"understood_as": understood_as}) if understood_as else result

    def mentions_of(question: str) -> Sequence[Mention] | None:
        ext = extractor()
        if ext is None:
            return None
        try:
            return ext(question)
        except Exception as exc:  # model down, timed out or unparseable: fall back to the deterministic answer
            log.warning("cascade question extractor failed: %s", exc)
            return None

    @app.get("/cascade/origins", response_model=OriginsResponse, response_model_exclude_none=True)
    def origins(q: str = Query(min_length=2, max_length=120), branch: str = "main"):
        return OriginsResponse(query=q, candidates=resolve(q, catalog(branch), MAX_CANDIDATES))

    @app.post("/cascade", response_model=CascadeResponse, response_model_exclude_none=True)
    def cascade(req: CascadeRequest):
        return engine().compute(parse_ref(req.branch), req.origin_id, req.min_severity)

    @app.post("/cascade/ask", response_model=CascadeResponse, response_model_exclude_none=True)
    def ask(req: CascadeAskRequest):
        cat = catalog(req.branch)
        candidates = resolve(req.question, cat, MAX_CANDIDATES)
        chosen = pick(candidates)
        if chosen is not None:
            return run(req, chosen)
        mentions = mentions_of(req.question)
        if mentions is None:  # no model: answer from the deterministic candidates alone
            return _reject("Several places match: choose one", candidates) if candidates else _reject(NOT_RECOGNISED)
        groups: list[Sequence[OriginCandidate]] = []
        hits: dict[str, tuple[OriginCandidate, str]] = {}
        for m in mentions:
            found = resolve(m.name, cat, MAX_CANDIDATES)
            hit = _pick_with_hint(found, m.kind)
            if hit is not None:
                hits.setdefault(hit.node.id, (hit, m.name))
            groups.append(found)
        if len(hits) == 1:
            hit, name = next(iter(hits.values()))
            return run(req, hit, understood_as=name)
        if hits:  # the question names several places that all exist: the operator picks one
            return _reject("Several places match: choose one", [h for h, _ in hits.values()])
        merged = _merge([*groups, candidates])
        if merged:
            return _reject("Several places match: choose one", merged)
        if mentions:
            names = ", ".join(f'"{m.name}"' for m in mentions)
            verb = "is" if len(mentions) == 1 else "are"
            return _reject(f"{names} {verb} not connected to anything in the TuringDB graph dataset")
        return _reject(NOT_RECOGNISED)
