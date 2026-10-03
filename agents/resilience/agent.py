"""The recovery agent: one bounded model loop that compares prepared plans and executes one of them.

The model never gets raw graph access. Its tools return figures that Python measured (simulate()), and it can
only execute a candidate it has evaluated; execution itself is Python (the branch lab). Model calls are bounded:
at most MAX_STEPS turns, each a single HTTP attempt on the configured model (no retry onto another model or
provider). If the provider fails or the loop ends without a valid choice, the prepared deterministic plan (the
top-ranked candidate) is executed and labelled as a fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agents.engine import Agent, Step, Tool
from agents.llm import LLMError
from agents.resilience.candidates import CandidateSet
from agents.resilience.exercises import Exercise
from agents.resilience.explain import key_paths
from agents.resilience.network import Network
from agents.resilience.simulate import Outcome

log = logging.getLogger("agents.resilience")
MAX_STEPS = 6
MAX_TOKENS = 500
NAME = "recovery"
PATH_PREVIEW = 6

SYSTEM = """You are the recovery agent for a fictional London–Dover–Paris resilience exercise. You handle exactly
three exercises: Dover Strait maritime closure (72 h), Kent-wide grid outage (48 h) and London/Croydon critical
infrastructure loss (168 h). Recovery candidates were prepared and validated from the graph's own recovery options;
every figure you see was measured by a deterministic simulator.
Rules:
- Never invent resources, capacities or impact figures; quote only numbers returned by tools.
- Evaluate a candidate before executing it. Execute exactly one candidate, then finish.
- Prefer the plan that best protects essential (priority-1) demand; weigh overall service, cargo, resource use
  (stock, generators, aircraft) and cost. A plan that spends reserves for little gain is worse.
Typical sequence: list_candidates -> compare_plans -> execute_plan -> finish {"choice": id, "rationale": text}."""


class ChatModel(Protocol):
    """FeatherlessLLM-compatible: `chat(messages, agent=, temperature=, max_tokens=, bounded=)` and `model`."""

    @property
    def model(self) -> str: ...

    def chat(self, messages: list[dict[str, str]], **kw: Any) -> str: ...


class _Bounded:
    """Every engine turn is one bounded call on the configured model; counts calls for the record."""

    def __init__(self, llm: ChatModel) -> None:
        self._llm = llm
        self.calls = 0

    @property
    def model(self) -> str:
        return str(self._llm.model)

    def chat(self, messages: list[dict[str, str]], **kw: Any) -> str:
        self.calls += 1
        return self._llm.chat(messages, agent=NAME, temperature=kw.get("temperature", 0.1),
                              max_tokens=MAX_TOKENS, bounded=True)


@dataclass
class Decision:
    mode: str  # agent | fallback
    plan_id: str
    rationale: str
    model: str | None
    calls: int
    reason: str | None = None  # why the fallback was used
    steps: list[dict] = field(default_factory=list)
    execution: dict | None = None


def _pct(x: float) -> float:
    return round(100 * x, 1)


def summary(o: Outcome) -> dict:
    m, c = o.metrics, o.consumption
    return {
        "essential_fulfilment_pct": _pct(m.essential_fulfilment), "overall_fulfilment_pct": _pct(m.overall_fulfilment),
        "cargo_on_time_t": m.cargo_on_time_t, "cargo_delayed_t": m.cargo_delayed_t, "cargo_unmet_t": m.cargo_unmet_t,
        "facilities_affected_at_end": m.affected_at_end, "capabilities_below_minimum": m.capabilities_below_minimum,
        "stock_released_t": c.stock_released_t, "generators": c.generators, "aircraft_sorties": c.aircraft_sorties,
        "cost_units": m.cost_units,
    }


class Toolbox:
    """Typed tools over one prepared exercise. `executor(plan_id)` builds and verifies the recovery branch."""

    def __init__(self, net: Network, ex: Exercise, cands: CandidateSet, executor: Callable[[str], dict]) -> None:
        self.net, self.ex, self.cands, self.executor = net, ex, cands, executor
        self.evaluated: set[str] = set()
        self.executed: tuple[str, str, dict] | None = None

    def inspect_exercise(self) -> dict:
        d = self.cands.disruption
        return {
            "exercise": self.ex.title, "window_hours": self.ex.hours, "initial_failures": len(d.initial),
            "without_recovery": summary(d),
            "dependency_paths": [" -> ".join(s.name for s in p.steps[:PATH_PREVIEW])
                                 + (" -> ..." if len(p.steps) > PATH_PREVIEW else "") for p in key_paths(self.net, d)],
            "unavailable_alternatives": list(self.cands.excluded)[:PATH_PREVIEW],
        }

    def list_candidates(self) -> dict:
        return {"candidates": [{"id": c.plan.plan_id, "title": c.plan.title, "summary": c.plan.summary,
                                "actions": len(c.plan.actions)} for c in self.cands.candidates]}

    def evaluate_plan(self, candidate_id: str) -> dict:
        c = self.cands.get(str(candidate_id))
        self.evaluated.add(c.plan.plan_id)
        return {"id": c.plan.plan_id, "measured": summary(c.outcome),
                "without_recovery": summary(self.cands.disruption)}

    def compare_plans(self, candidate_ids: list[str] | None = None) -> dict:
        ids = [str(i) for i in (candidate_ids or [c.plan.plan_id for c in self.cands.candidates])]
        rows = []
        for i in ids:
            c = self.cands.get(i)
            self.evaluated.add(i)
            rows.append({"id": i, "title": c.plan.title, **summary(c.outcome)})
        return {"without_recovery": summary(self.cands.disruption), "candidates": rows,
                "deterministic_rank": [c.plan.plan_id for c in self.cands.candidates if c.plan.plan_id in ids]}

    def execute_plan(self, candidate_id: str, rationale: str = "") -> dict:
        cid = str(candidate_id)
        self.cands.get(cid)
        if cid not in self.evaluated:
            return {"error": f"evaluate {cid} (evaluate_plan or compare_plans) before executing it"}
        if self.executed:
            return {"error": f"{self.executed[0]} is already executed; finish now"}
        result = self.executor(cid)
        self.executed = (cid, str(rationale), result)
        return {"executed": cid, **result}

    def tools(self) -> list[Tool]:
        return [
            Tool("inspect_exercise", "The event, its measured impact without recovery, key dependency paths and "
                 "unavailable alternatives.", lambda: self.inspect_exercise()),
            Tool("list_candidates", "The prepared, validated recovery candidates.", lambda: self.list_candidates()),
            Tool("evaluate_plan", "Measured results of one candidate.", self.evaluate_plan,
                 {"candidate_id": "id from list_candidates"}),
            Tool("compare_plans", "Measured results of several candidates side by side.", self.compare_plans,
                 {"candidate_ids": "list of ids (omit for all)"}),
            Tool("execute_plan", "Apply one evaluated candidate in a new recovery branch.", self.execute_plan,
                 {"candidate_id": "id", "rationale": "one or two sentences citing measured figures"}),
        ]

    def honour_finish(self, result: dict | None) -> str | None:
        """Execute a `finish {"choice": id}` naming an evaluated candidate; otherwise say why nothing ran."""
        if self.executed:
            return None
        choice = str((result or {}).get("choice") or "")
        if choice in self.evaluated:
            self.execute_plan(choice, str((result or {}).get("rationale") or ""))
            return None
        return "the agent finished without executing an evaluated candidate"


def decide(net: Network, ex: Exercise, cands: CandidateSet, executor: Callable[[str], dict],
           model: ChatModel | None, on_step: Callable[[str, Step], None] | None = None,
           unavailable_reason: str | None = None) -> Decision:
    """Run the bounded agent; fall back to the prepared deterministic plan when the provider cannot help."""
    box = Toolbox(net, ex, cands, executor)
    steps: list[Step] = []
    reason = unavailable_reason or ("no model configured" if model is None else None)
    bounded = _Bounded(model) if model is not None else None
    name: str | None = None
    if bounded is not None:
        def record(agent_name: str, step: Step) -> None:
            steps.append(step)
            if on_step:
                on_step(agent_name, step)
        try:
            name = bounded.model
            agent = Agent(NAME, bounded, SYSTEM, box.tools(), max_steps=MAX_STEPS, temperature=0.1)  # type: ignore[arg-type]
            trace = agent.run(f"Exercise: {ex.title} ({ex.hours:g} h). Choose and execute one recovery plan.", record)
            reason = box.honour_finish(trace.result)
        except LLMError as exc:  # message bodies may echo provider payloads: record only the class
            reason = f"model provider unavailable ({type(exc).__name__})"
            log.warning("recovery agent provider failure: %s", type(exc).__name__)
    record_steps = [{"thought": s.thought, "action": s.action, "args": s.args} for s in steps]
    calls = bounded.calls if bounded else 0
    if box.executed:
        cid, rationale, result = box.executed
        return Decision("agent", cid, rationale or "Chosen by the recovery agent.", name, calls, None,
                        record_steps, result)
    best = cands.candidates[0].plan.plan_id
    return Decision("fallback", best, "Prepared deterministic plan: the highest-ranked candidate by measured "
                    "essential fulfilment, then overall fulfilment, cargo and cost.", name, calls,
                    reason or "the agent did not execute a candidate within its step budget",
                    record_steps, executor(best))
