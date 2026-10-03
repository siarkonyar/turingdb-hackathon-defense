"""OpsMap API routes that drive the LLM agents (threat / defence / scenario) over the live `theatre` graph.

The agents build TuringDB branches; those branches then show up in the existing `/branches` and `/diff`
endpoints, so the OpsMap map visualises an agent's scenario with no extra plumbing. Mounted only when the
backend is the live TuringDB one (the agents need a real graph and the Featherless key).
"""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI
from pydantic import BaseModel, Field

from api.config import Settings

log = logging.getLogger("opsmap.agents")

MANCHESTER_EXAMPLE = ("A catastrophic event has destroyed everything across Manchester. How would this "
                      "affect the rest of the city and its connected infrastructure?")


class ScenarioRequest(BaseModel):
    question: str = Field(min_length=4, max_length=800)
    max_steps: int = Field(default=16, ge=2, le=28)


class DefenceRequest(BaseModel):
    threat_branch: str = Field(min_length=1, max_length=16)
    max_steps: int = Field(default=16, ge=2, le=28)


class RedBlueRequest(BaseModel):
    threat_steps: int = Field(default=16, ge=2, le=28)
    defence_steps: int = Field(default=16, ge=2, le=28)


class _Hub:
    """Lazily builds the agent lab (TuringDB supervisor + branch lab + Featherless client), once."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lab = None
        self._lock = threading.Lock()
        self._error: str | None = None

    def lab(self):
        from agents.orchestrator import Lab

        with self._lock:
            if self._lab is None:
                self._lab = Lab.create()
            return self._lab

    def status(self) -> dict:
        from agents.config import load_agent_settings
        from agents.llm import FeatherlessLLM, LLMUnavailable

        cfg = load_agent_settings()
        if not cfg.api_key:
            return {"available": False, "reason": "FEATHERLESS_API_KEY is not set"}
        try:
            model = self._lab.llm.model if self._lab else FeatherlessLLM(cfg).model
            return {"available": True, "model": model, "graph": cfg.graph}
        except LLMUnavailable as exc:
            return {"available": False, "reason": str(exc)}
        except Exception as exc:  # network/listing hiccup: report, don't crash the API
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def register_agent_routes(app: FastAPI, settings: Settings) -> None:
    hub = _Hub(settings)

    @app.get("/agent/status")
    def agent_status() -> dict:
        return hub.status()

    @app.post("/agent/scenario")
    def agent_scenario(req: ScenarioRequest) -> dict:
        from agents.orchestrator import run_scenario_question

        out = run_scenario_question(hub.lab(), req.question, steps=req.max_steps)
        result = out.get("result", {})
        return {"branch": out.get("branch"), "explanation": result.get("explanation"),
                "headline": result.get("headline"), "impact_diff": out.get("impact_diff"),
                "deep_supply": out.get("deep_supply"),
                "steps": [s["action"] for s in out["trace"]["steps"]], "model": out["trace"].get("model")}

    @app.post("/agent/threat")
    def agent_threat(req: RedBlueRequest) -> dict:
        from agents.threat import run_threat

        lab = hub.lab()
        trace = run_threat(lab.branches, lab.llm, max_steps=req.threat_steps)
        return {"result": trace.result, "steps": [s.action for s in trace.steps], "model": trace.model,
                "branches": [{"change_id": r.change_id, "label": r.label,
                              "loss_pct": None if r.loss is None else round(100 * r.loss, 1)}
                             for r in lab.branches.records() if r.role == "threat"]}

    @app.post("/agent/defence")
    def agent_defence(req: DefenceRequest) -> dict:
        from agents.defence import run_defence

        lab = hub.lab()
        trace = run_defence(lab.branches, lab.llm, req.threat_branch, max_steps=req.max_steps)
        return {"result": trace.result, "steps": [s.action for s in trace.steps], "model": trace.model}

    @app.post("/agent/redblue")
    def agent_redblue(req: RedBlueRequest) -> dict:
        from agents.orchestrator import run_red_blue

        res = run_red_blue(hub.lab(), req.threat_steps, req.defence_steps)
        return res.as_dict()

    log.info("agent routes mounted (/agent/status, /scenario, /threat, /defence, /redblue)")
