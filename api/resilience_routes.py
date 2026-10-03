"""Dover resilience exercises: the three supported scenarios, run as one background job each.

    GET  /resilience/exercises            the three suggestions (fixed scenario ids)
    POST /resilience/run {scenario_id}    -> {job_id}; one run at a time
    POST /resilience/ask {question}       free text -> a run for the event it describes, or a plain reply
    GET  /resilience/jobs/{id}?after=N    events after N: phase | disruption | agent_step | recovery | error | done

A run: disruption branch + dependency-degree cascade -> recovery agent compares prepared, measured candidates
-> chosen plan executed in a separate recovery branch (disruption replayed first) -> before/after report.
Mounted only for the `dover` graph on the live backend. Contract: docs/api.md "Dover resilience exercises".
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, Query

from agents.resilience.agent import ChatModel, decide
from agents.resilience.candidates import CandidateSet, prepare_candidates
from agents.resilience.exercises import EXERCISES, NO_MATCH_REPLY, Exercise, get_exercise, match_question
from agents.resilience.explain import benefits, cascade, compare, limitations, links
from agents.resilience.network import Network
from api.jobs import JobRegistry
from api.models import QueryTrace
from api.resilience_models import (AskRequest, AskResponse, ExerciseInfo, ExercisesResponse, JobEventView, JobView,
                                   RunRequest, RunStarted)
from api.resilience_view import cascade_view, disruption_view, offline_reach, reach_query, recovery_view

log = logging.getLogger("opsmap.resilience")
Emit = Callable[[str, dict], None]
ModelFactory = Callable[[], tuple[ChatModel | None, str | None]]


def featherless_model() -> tuple[ChatModel | None, str | None]:
    """The configured Featherless model, or the reason it is unavailable (never the key itself)."""
    from agents.config import load_agent_settings
    from agents.llm import FeatherlessLLM, LLMUnavailable

    try:
        return FeatherlessLLM(load_agent_settings(), timeout_s=60.0), None
    except LLMUnavailable as exc:
        return None, str(exc)


class ExerciseRunner:
    """Runs one exercise end to end over a lab (live ResilienceLab, or a test double with the same methods)."""

    def __init__(self, lab: Any, model_factory: ModelFactory = featherless_model) -> None:
        self.lab = lab
        self.model_factory = model_factory
        self._cands: dict[str, CandidateSet] = {}
        self._lock = threading.Lock()

    def network(self) -> Network:
        return self.lab.network()

    def candidates(self, ex: Exercise) -> CandidateSet:
        with self._lock:
            if ex.scenario_id not in self._cands:
                self._cands[ex.scenario_id] = prepare_candidates(self.network(), ex)
            return self._cands[ex.scenario_id]

    def _reach(self, ex: Exercise, outcome: Any) -> tuple[tuple[str, int, float | None], list[QueryTrace]]:
        cypher = reach_query(ex.scenario_id)
        timed = getattr(self.lab, "timed", None)
        if timed is None:  # offline double: the same count, computed in Python, with no engine time
            return (cypher, offline_reach(self.network(), outcome), None), []
        frame, traces = timed(cypher)
        return (cypher, int(frame["reached"].iloc[0]), traces[-1].ms), traces

    def run(self, scenario_id: str, emit: Emit) -> dict:
        started = time.perf_counter()
        ex = get_exercise(scenario_id)
        net = self.network()
        emit("phase", {"phase": "disruption", "message": f"Applying {ex.title} in a new disruption branch"})
        cands = self.candidates(ex)
        layers = cascade(net, cands.disruption)
        record = self.lab.disrupt(ex, cands.disruption, [h for layer in layers for h in layer])
        reach, traces = self._reach(ex, cands.disruption)
        latency = round((time.perf_counter() - started) * 1000, 1)
        view = cascade_view(net, ex, cands.disruption, layers, record.branch, reach, traces, latency)
        emit("disruption", disruption_view(net, ex, cands, view, record).model_dump(mode="json"))
        emit("phase", {"phase": "recovery",
                       "message": f"Recovery agent comparing {len(cands.candidates)} prepared, measured plans"})
        executed: dict[str, Any] = {}

        def executor(plan_id: str) -> dict:
            cand = cands.get(plan_id)
            cmp = compare(net, cands.disruption, cand.outcome)
            rec = self.lab.recover(ex, cand.plan, cand.outcome, cmp, record.branch)
            executed[plan_id] = (rec, cmp)
            return {"branch": rec.branch, "verified": rec.verified}

        def step(_agent: str, s: Any) -> None:
            emit("agent_step", {"thought": s.thought, "action": s.action, "args": s.args})

        model, why = self.model_factory()
        decision = decide(net, ex, cands, executor, model, on_step=step, unavailable_reason=why)
        rec, cmp = executed[decision.plan_id]
        chosen = cands.get(decision.plan_id)
        result = recovery_view(net, ex, cands, decision, rec, record.branch, cmp,
                               benefits(net, ex, chosen.plan, chosen.outcome),
                               limitations(net, chosen.outcome, cands.excluded), links(net, chosen.outcome))
        payload = result.model_dump(mode="json")
        emit("recovery", payload)
        return payload


def _default_runner(app: FastAPI) -> ExerciseRunner:
    from agents.resilience.lab import ResilienceLab

    return ExerciseRunner(ResilienceLab(app.state.backend))


def register_resilience_routes(app: FastAPI,
                               runner_factory: Callable[[FastAPI], ExerciseRunner] | None = None) -> None:
    holder: dict[str, Any] = {}
    jobs = JobRegistry(max_running=1)  # one exercise at a time: one model caller, one writer

    def runner() -> ExerciseRunner:
        if "runner" not in holder:
            holder["runner"] = (runner_factory or _default_runner)(app)
        return holder["runner"]

    @app.get("/resilience/exercises", response_model=ExercisesResponse)
    def exercises():
        return ExercisesResponse(exercises=[
            ExerciseInfo(scenario_id=e.scenario_id, title=e.title, prompt=e.prompt, kind=e.kind,  # type: ignore[arg-type]
                         hours=e.hours) for e in EXERCISES.values()])

    @app.post("/resilience/run", response_model=RunStarted)
    def run(req: RunRequest):
        r = runner()
        job = jobs.start("resilience", lambda job: r.run(req.scenario_id, job.emit))
        log.info("resilience run %s started for %s", job.id, req.scenario_id)
        return RunStarted(job_id=job.id, scenario_id=req.scenario_id)

    @app.post("/resilience/ask", response_model=AskResponse, response_model_exclude_none=True)
    def ask(req: AskRequest):
        ex = match_question(req.question)
        if ex is None:
            return AskResponse(reply=NO_MATCH_REPLY)
        r = runner()
        job = jobs.start("resilience", lambda job: r.run(ex.scenario_id, job.emit))
        log.info("resilience question %r -> %s (run %s)", req.question[:80], ex.scenario_id, job.id)
        return AskResponse(job_id=job.id, scenario_id=ex.scenario_id, title=ex.title,  # type: ignore[arg-type]
                           hours=ex.hours)

    @app.get("/resilience/jobs/{job_id}", response_model=JobView, response_model_exclude_none=True)
    def job(job_id: str, after: int = Query(default=0, ge=0)):
        j = jobs.get(job_id)
        events = j.since(after)
        return JobView(job_id=j.id, status=j.status,
                       events=[JobEventView(id=e.id, type=e.type, data=e.data) for e in events],
                       next=after + len(events))
