"""The agent side of the API: one lazily built lab (TuringDB supervisor + branch lab + Featherless client)
and the agent functions the routes run as background jobs. The CLI (agents.orchestrator, agents.match)
calls the same functions; tests replace this hub with a fake."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from agents.engine import Step, _trim

log = logging.getLogger("opsmap.agents")

StepFn = Callable[[str, Step], None]


class AgentHub:
    def __init__(self, matches_dir: Path | None = None) -> None:
        from agents.match import MATCHES_DIR

        self.matches_dir = Path(os.environ.get("OPSMAP_MATCHES_DIR") or matches_dir or MATCHES_DIR)
        self._lab = None
        self._board = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lazily built pieces (worker threads)

    def lab(self):
        from agents.orchestrator import Lab

        with self._lock:
            if self._lab is None:
                self._lab = Lab.create()
            return self._lab

    def board(self):
        from agents.match_board import LabBoard

        lab = self.lab()
        with self._lock:
            if self._board is None:
                self._board = LabBoard(lab.branches)
            return self._board

    def llm(self):
        return self.lab().llm  # raises LLMUnavailable with the reason

    def injector(self):
        from agents.match_board import scenario_injector

        return scenario_injector(self.lab())

    def status(self) -> dict:
        from agents.config import load_agent_settings
        from agents.llm import FeatherlessLLM, LLMUnavailable

        cfg = load_agent_settings()
        if self._lab is not None and self._lab.llm_or_none is None:
            return {"available": False, "reason": self._lab.llm_error, "graph": cfg.graph}
        if not cfg.api_key:
            return {"available": False, "reason": "FEATHERLESS_API_KEY is not set", "graph": cfg.graph}
        try:
            model = self._lab.llm.model if self._lab else FeatherlessLLM(cfg).model
            return {"available": True, "model": model, "graph": cfg.graph}
        except LLMUnavailable as exc:
            return {"available": False, "reason": str(exc), "graph": cfg.graph}
        except Exception as exc:  # network/listing hiccup: report, don't crash the API
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}", "graph": cfg.graph}

    # ------------------------------------------------------------------ one-shot agents

    def scenario(self, question: str, steps: int, on_step: StepFn) -> dict:
        from agents.orchestrator import run_scenario_question

        out = run_scenario_question(self.lab(), question, steps=steps, on_step=on_step)
        result = out.get("result", {})
        return {"branch": out.get("branch"), "explanation": result.get("explanation"),
                "headline": result.get("headline"), "impact_diff": out.get("impact_diff"),
                "deep_supply": out.get("deep_supply"),
                "steps": [s["action"] for s in out["trace"]["steps"]], "model": out["trace"].get("model")}

    def threat(self, steps: int, on_step: StepFn) -> dict:
        from agents.threat import run_threat

        lab = self.lab()
        trace = run_threat(lab.branches, lab.llm, max_steps=steps, on_step=on_step)
        return {"result": trace.result, "steps": [s.action for s in trace.steps], "model": trace.model,
                "branches": [{"change_id": r.change_id, "label": r.label,
                              "loss_pct": None if r.loss is None else round(100 * r.loss, 1)}
                             for r in lab.branches.records() if r.role == "threat"]}

    def defence(self, threat_branch: str, steps: int, on_step: StepFn) -> dict:
        from agents.defence import run_defence

        lab = self.lab()
        trace = run_defence(lab.branches, lab.llm, threat_branch, max_steps=steps, on_step=on_step)
        return {"result": trace.result, "steps": [s.action for s in trace.steps], "model": trace.model}

    def redblue(self, threat_steps: int, defence_steps: int, on_step: StepFn) -> dict:
        from agents.orchestrator import run_red_blue

        res = run_red_blue(self.lab(), threat_steps, defence_steps, on_step=on_step).as_dict()
        return {k: v for k, v in res.items() if k not in ("threat_trace", "defence_trace")}


def step_event(agent: str, step: Step) -> dict:
    """A compact, UI-sized view of one agent step."""
    return {"agent": agent, "action": step.action, "thought": step.thought[:300],
            "selection": (step.observation.get("selection", step.observation)
                          if step.action == "blue_selection" and isinstance(step.observation, dict) else None),
            "args": {k: _short(v) for k, v in (step.args or {}).items()}, "observation": _trim(step.observation, 400)}


def _short(value: Any) -> Any:
    text = str(value)
    return value if len(text) <= 200 else text[:200] + "…"
