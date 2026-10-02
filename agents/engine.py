"""The agent loop: a model drives a bounded ReAct cycle over a set of tools.

Each turn the model returns one JSON action; the engine runs the matching tool and feeds back the
observation. Tools are plain Python callables returning JSON-serialisable results. The loop ends when the
model calls `finish` or the step budget runs out. This is model-agnostic: it only needs FeatherlessLLM.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agents.llm import FeatherlessLLM, LLMError, parse_action

log = logging.getLogger("agents.engine")


@dataclass
class Tool:
    name: str
    description: str
    run: Callable[..., Any]
    schema: dict[str, str] = field(default_factory=dict)  # arg name -> description


@dataclass
class Step:
    thought: str
    action: str
    args: dict
    observation: Any


@dataclass
class Trace:
    agent: str
    steps: list[Step] = field(default_factory=list)
    result: dict | None = None
    model: str | None = None

    def as_dict(self) -> dict:
        return {
            "agent": self.agent, "model": self.model,
            "steps": [{"thought": s.thought, "action": s.action, "args": s.args,
                       "observation": _trim(s.observation)} for s in self.steps],
            "result": self.result,
        }


def _trim(obs: Any, limit: int = 1200) -> Any:
    text = obs if isinstance(obs, str) else json.dumps(obs, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


PROTOCOL = (
    "You act by replying with exactly ONE JSON object and nothing else:\n"
    '{"thought": "<one sentence of reasoning>", "action": "<tool name>", "args": {<arguments>}}\n'
    "Do not wrap it in prose. Do not emit more than one object. After each action you receive an "
    "OBSERVATION; use it to choose the next action. Call `finish` when you are done."
)


class Agent:
    def __init__(self, name: str, llm: FeatherlessLLM, system: str, tools: list[Tool],
                 max_steps: int = 14, temperature: float = 0.2) -> None:
        self.name, self.llm, self.system = name, llm, system
        self.tools = {t.name: t for t in tools}
        self.tools.setdefault("finish", Tool("finish", "Finish and return your result.",
                                             lambda **kw: kw, {"<any>": "your final structured result"}))
        self.max_steps, self.temperature = max_steps, temperature

    def _tool_docs(self) -> str:
        lines = []
        for t in self.tools.values():
            args = "; ".join(f"{k}: {v}" for k, v in t.schema.items()) or "none"
            lines.append(f"- {t.name}({args}) — {t.description}")
        return "\n".join(lines)

    def run(self, task: str) -> Trace:
        trace = Trace(agent=self.name)
        messages = [
            {"role": "system", "content": f"{self.system}\n\nTOOLS:\n{self._tool_docs()}\n\n{PROTOCOL}"},
            {"role": "user", "content": task},
        ]
        for step_no in range(self.max_steps):
            try:
                reply = self.llm.chat(messages, agent=self.name, temperature=self.temperature)
            except LLMError:
                raise
            trace.model = self.llm.model
            try:
                action = parse_action(reply)
            except ValueError as exc:
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"FORMAT ERROR: {exc}. Reply with one JSON action object."})
                continue
            name, args = action["action"], action.get("args", {})
            thought = str(action.get("thought", ""))
            if name == "finish":
                trace.result = args
                trace.steps.append(Step(thought, name, args, "done"))
                return trace
            tool = self.tools.get(name)
            if tool is None:
                obs: Any = {"error": f"unknown tool {name!r}; available: {sorted(self.tools)}"}
            else:
                try:
                    obs = tool.run(**args)
                except TypeError as exc:
                    obs = {"error": f"bad arguments for {name}: {exc}"}
                except Exception as exc:  # tool failures are observations the model can recover from
                    obs = {"error": f"{type(exc).__name__}: {exc}"}
            trace.steps.append(Step(thought, name, args, obs))
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": "OBSERVATION:\n" + json.dumps(obs, default=str)[:3000]})
            log.info("[%s] step %d: %s -> %s", self.name, step_no, name, _trim(obs, 160))
        trace.result = trace.result or {"note": "step budget exhausted", "incomplete": True}
        return trace
