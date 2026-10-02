"""Featherless AI chat client (OpenAI-compatible) and the JSON action protocol the agents speak.

The key comes from FEATHERLESS_API_KEY and is only ever placed in the Authorization header.
Agents do not depend on native function calling (support varies per Featherless model): each turn the
model answers with one JSON object `{"thought": ..., "action": ..., "args": {...}}`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from agents.config import MODEL_PREFERENCE, AgentSettings

log = logging.getLogger("agents.llm")
_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 5


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """No key, host unreachable, or no model the account may use."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    by_agent: dict[str, int] = field(default_factory=dict)


class FeatherlessLLM:
    def __init__(self, settings: AgentSettings, timeout_s: float = 180.0) -> None:
        if not settings.api_key:
            raise LLMUnavailable("FEATHERLESS_API_KEY is not set")
        self._base = settings.base_url
        self._pinned = settings.model
        self._http = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=20.0),
                                  headers={"Authorization": f"Bearer {settings.api_key}"})
        self._model: str | None = settings.model
        self._lock = threading.Lock()  # Featherless plans limit concurrent requests; agents run one call at a time
        self.usage = Usage()

    # ------------------------------------------------------------------ model selection

    def available_models(self) -> set[str]:
        try:
            resp = self._http.get(f"{self._base}/models")
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"cannot reach {self._base}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise LLMUnavailable(f"Featherless refused the API key (HTTP {resp.status_code})")
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("data", body) if isinstance(body, dict) else body
        return {str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")}

    def _candidates(self) -> list[str]:
        if self._pinned:
            return [self._pinned]
        try:
            listed = self.available_models()
        except LLMUnavailable:
            raise
        except Exception as exc:  # listing is a convenience: fall back to trying the preference list
            log.warning("model listing failed (%s); trying the preference list", exc)
            return list(MODEL_PREFERENCE)
        ranked = [m for m in MODEL_PREFERENCE if m in listed]
        return ranked or list(MODEL_PREFERENCE)

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = self._candidates()[0]
        return self._model

    # ------------------------------------------------------------------ calls

    def chat(self, messages: list[dict[str, str]], *, agent: str = "agent", temperature: float = 0.2,
             max_tokens: int = 1200) -> str:
        with self._lock:
            return self._chat_locked(messages, agent, temperature, max_tokens)

    def _chat_locked(self, messages: list[dict[str, str]], agent: str, temperature: float, max_tokens: int) -> str:
        tried: list[str] = []
        candidates = [self.model] + [m for m in self._candidates() if m != self.model]
        last_error = "no model tried"
        for model in candidates:
            tried.append(model)
            try:
                text = self._post(model, messages, temperature, max_tokens, agent)
                self._model = model
                return text
            except _ModelRefused as exc:  # plan / model not available: try the next model
                last_error = str(exc)
                log.warning("model %s refused: %s", model, exc)
        raise LLMUnavailable(f"no usable Featherless model (tried {tried}): {last_error}")

    def _post(self, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int,
              agent: str) -> str:
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        delay = 2.0
        for attempt in range(MAX_RETRIES):
            started = time.perf_counter()
            try:
                resp = self._http.post(f"{self._base}/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                if attempt == MAX_RETRIES - 1:
                    raise LLMUnavailable(f"cannot reach Featherless: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (401, 403) and "model" not in resp.text.lower():
                raise LLMUnavailable(f"Featherless refused the API key (HTTP {resp.status_code})")
            if resp.status_code in (400, 403, 404) and _mentions_model(resp.text):
                raise _ModelRefused(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                log.info("Featherless HTTP %s, retrying in %.0fs", resp.status_code, delay)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise LLMError(f"Featherless HTTP {resp.status_code}: {resp.text[:300]}")
            body = resp.json()
            usage = body.get("usage") or {}
            self.usage.calls += 1
            self.usage.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.usage.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.usage.seconds += time.perf_counter() - started
            self.usage.by_agent[agent] = self.usage.by_agent.get(agent, 0) + 1
            try:
                return str(body["choices"][0]["message"]["content"] or "")
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"unexpected Featherless response: {str(body)[:300]}") from exc
        raise LLMError("Featherless retries exhausted")


class _ModelRefused(LLMError):
    pass


def _mentions_model(text: str) -> bool:
    low = text.lower()
    return "model" in low and any(w in low for w in ("not found", "not available", "unavailable", "plan", "access",
                                                     "does not exist", "unsupported", "not supported", "gated"))


# ---------------------------------------------------------------------- JSON action protocol

def strip_reasoning(text: str) -> str:
    text = _THINK.sub("", text)
    if "<think>" in text:  # unterminated reasoning block: keep what follows the last tag
        text = text.rsplit("</think>", 1)[-1] if "</think>" in text else text.split("<think>", 1)[0]
    return text.strip()


def _balanced_objects(text: str) -> list[str]:
    """Every top-level {...} span, string-aware."""
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append(text[start:i + 1])
    return out


def parse_action(text: str) -> dict[str, Any]:
    """Extract the action object from a model reply. Raises ValueError with a message the model can act on."""
    clean = strip_reasoning(text)
    spans = [m.group(1) for m in _FENCE.finditer(clean)] + [clean]
    for span in spans:
        for obj in _balanced_objects(span):
            try:
                data = json.loads(obj)
            except json.JSONDecodeError:
                try:  # trailing commas are the most common slip
                    data = json.loads(re.sub(r",\s*([}\]])", r"\1", obj))
                except json.JSONDecodeError:
                    continue
            if isinstance(data, dict) and isinstance(data.get("action"), str):
                args = data.get("args")
                data["args"] = args if isinstance(args, dict) else {}
                return data
    raise ValueError('reply was not one JSON object of the form {"thought": "...", "action": "<tool>", "args": {...}}')
