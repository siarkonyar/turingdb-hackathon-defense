"""OpsMap API routes that drive the LLM agents and the red-vs-blue wargame over the live `theatre` graph.

Every agent action is a background job: a POST starts it and returns an id at once, and the client follows
its progress on a server-sent-events stream. Agents build TuringDB branches, which then show up in the
existing `/branches` and `/diff` endpoints, so the map follows them with no extra plumbing. Mounted only
on the live TuringDB backend (the agents need a real graph). Contract: docs/api.md.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.agent_hub import AgentHub, step_event
from api.config import Settings
from api.jobs import Job, JobRegistry, sse_stream
from api.refs import parse_ref
from api.support import Conflict, NotFound

log = logging.getLogger("opsmap.agents")

MAX_ROUNDS = 6
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class ScenarioRequest(BaseModel):
    question: str = Field(min_length=4, max_length=800)
    max_steps: int = Field(default=16, ge=2, le=28)


class DefenceRequest(BaseModel):
    threat_branch: str = Field(min_length=1, max_length=16, pattern=r"^\d{1,9}$")
    max_steps: int = Field(default=16, ge=2, le=28)


class RedBlueRequest(BaseModel):
    threat_steps: int = Field(default=16, ge=2, le=28)
    defence_steps: int = Field(default=16, ge=2, le=28)


class MatchRequest(BaseModel):
    base_branch: str = Field(default="main", min_length=1, max_length=16)
    rounds: int = Field(default=3, ge=1, le=MAX_ROUNDS)

    @field_validator("base_branch")
    @classmethod
    def _branch_head(cls, value: str) -> str:
        ref = parse_ref(value)
        if ref.commit is not None:
            raise ValueError("a match starts from a branch head, not a commit")
        return ref.branch


class InjectRequest(BaseModel):
    text: str = Field(min_length=3, max_length=400)


class ReplayRequest(BaseModel):
    file: str = Field(min_length=1, max_length=70)
    speed: float = Field(default=1.0, gt=0, le=20)


class _Lazy:
    """Resolves a hub factory on first use, i.e. inside the worker thread, never in the request."""

    def __init__(self, factory) -> None:
        self._factory, self._value = factory, None

    def __getattr__(self, name: str) -> Any:
        if self._value is None:
            self._value = self._factory()
        return getattr(self._value, name)


class _ReplayHandle:
    def __init__(self) -> None:
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()


def register_agent_routes(app: FastAPI, settings: Settings | None = None, hub: Any = None) -> None:
    hub = hub or AgentHub()
    jobs = JobRegistry()
    app.state.agent_hub, app.state.agent_jobs = hub, jobs

    def stream(job: Job, last_event_id: str | None) -> StreamingResponse:
        return StreamingResponse(sse_stream(job, last_event_id), media_type="text/event-stream", headers=SSE_HEADERS)

    def agent_job(kind: str, run) -> dict:
        def work(job: Job) -> dict:
            result = run(lambda agent, step: job.emit("step", step_event(agent, step)))
            job.emit("result", result)
            return result
        return {"job_id": jobs.start(kind, work).id}

    # ------------------------------------------------------------------ one-shot agents (jobs)

    @app.get("/agent/status")
    def agent_status() -> dict:
        return hub.status()

    @app.post("/agent/scenario", status_code=202)
    def agent_scenario(req: ScenarioRequest) -> dict:
        return agent_job("scenario", lambda on_step: hub.scenario(req.question, req.max_steps, on_step))

    @app.post("/agent/threat", status_code=202)
    def agent_threat(req: RedBlueRequest) -> dict:
        return agent_job("threat", lambda on_step: hub.threat(req.threat_steps, on_step))

    @app.post("/agent/defence", status_code=202)
    def agent_defence(req: DefenceRequest) -> dict:
        return agent_job("defence", lambda on_step: hub.defence(req.threat_branch, req.max_steps, on_step))

    @app.post("/agent/redblue", status_code=202)
    def agent_redblue(req: RedBlueRequest) -> dict:
        return agent_job("redblue", lambda on_step: hub.redblue(req.threat_steps, req.defence_steps, on_step))

    @app.get("/agent/jobs/{job_id}")
    def agent_job_status(job_id: str) -> dict:
        return jobs.get(job_id).snapshot()

    @app.get("/agent/jobs/{job_id}/events")
    def agent_job_events(job_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        return stream(jobs.get(job_id), last_event_id)

    # ------------------------------------------------------------------ the wargame

    @app.post("/match", status_code=202)
    def start_match(req: MatchRequest) -> dict:
        from agents.match import Match

        bound: dict[str, Job] = {}

        def emit(kind: str, data: dict) -> None:
            if "job" in bound:
                bound["job"].emit(kind, data)

        match = Match(_Lazy(hub.board), req.base_branch, req.rounds, llm=_Lazy(hub.llm),
                      injector=lambda text, parent, llm: hub.injector()(text, parent, llm), emit=emit,
                      directory=hub.matches_dir)

        def work(job: Job) -> dict:
            bound["job"] = job
            try:
                hub.llm()  # fail fast with the reason, before any branch is built
            except Exception as exc:
                job.emit("error", {"message": f"LLM unavailable: {exc}", "replay_available": True})
                return {"status": "error"}
            return match.run()

        return {"match_id": jobs.start("match", work, handle=match, job_id=match.id).id}

    @app.post("/match/replay", status_code=202)
    def replay_match(req: ReplayRequest) -> dict:
        from agents.match import load_match, replay

        try:
            data = load_match(req.file, hub.matches_dir)
        except FileNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        handle = _ReplayHandle()

        def work(job: Job) -> dict:
            return replay(data, hub.board(), job.emit, speed=req.speed, stop=handle.stop_event)

        return {"match_id": jobs.start("replay", work, handle=handle).id}

    @app.get("/matches")
    def saved_matches() -> dict:
        from agents.match import list_matches

        return {"matches": list_matches(hub.matches_dir) if hub.matches_dir.exists() else []}

    def match_job(match_id: str) -> Job:
        job = jobs.get(match_id)
        if job.kind not in ("match", "replay"):
            raise NotFound(f"no match {match_id!r}")
        return job

    @app.get("/match/{match_id}")
    def match_status(match_id: str) -> dict:
        job = match_job(match_id)
        moves = [m.as_dict() for m in getattr(job.handle, "moves", [])]
        return {**job.snapshot(), "head": getattr(job.handle, "head", None), "moves": moves}

    @app.get("/match/{match_id}/events")
    def match_events(match_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        return stream(match_job(match_id), last_event_id)

    def control(match_id: str, action: str) -> dict:
        job = match_job(match_id)
        if job.finished:
            raise Conflict(f"match {match_id} is already {job.status}")
        fn = getattr(job.handle, action, None)
        if fn is None:
            raise Conflict(f"a {job.kind} cannot {action}")
        fn()
        return {"match_id": match_id, "action": action}

    @app.post("/match/{match_id}/inject", status_code=202)
    def inject(match_id: str, req: InjectRequest) -> dict:
        job = match_job(match_id)
        if job.kind != "match" or job.finished:
            raise Conflict(f"match {match_id} does not take injects ({job.kind}, {job.status})")
        try:
            queued = job.handle.inject(req.text)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        return {"match_id": match_id, "queued": queued}

    @app.post("/match/{match_id}/pause")
    def pause(match_id: str) -> dict:
        return control(match_id, "pause")

    @app.post("/match/{match_id}/resume")
    def resume(match_id: str) -> dict:
        return control(match_id, "resume")

    @app.post("/match/{match_id}/stop")
    def stop(match_id: str) -> dict:
        return control(match_id, "stop")

    log.info("agent routes mounted (/agent/*, /match*, /matches)")
