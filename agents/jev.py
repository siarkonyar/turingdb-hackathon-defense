"""Featherless Simple Jev choice client; no chat generation or graph writes.

One request, no retries: beta access/capacity failures must promptly return Blue to its usual flow.
Provider bodies and credentials are never included in diagnostics.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass

import httpx

from agents.config import load_agent_settings


@dataclass(frozen=True)
class JevSettings:
    enabled: bool = False
    model: str = "featherless-ai/gemma-4-26B-A4B-classifier"
    timeout_s: float = 15.0
    min_confidence: float = 0.0
    priorities: str = "Protect critical parts and priority programmes; respect the available intervention budget."


def load_jev_settings() -> JevSettings:
    load_agent_settings()  # loads .env without overriding operator environment
    def number(name, default, low, high):
        try:
            value = float(os.getenv(name, str(default)))
            return max(low, min(high, value)) if math.isfinite(value) else default
        except ValueError:
            return default
    return JevSettings(
        enabled=os.getenv("BLUE_JEV_ENABLED", "0") == "1",
        model=os.getenv("BLUE_JEV_MODEL", JevSettings.model),
        timeout_s=number("BLUE_JEV_TIMEOUT", 15.0, 0.1, 60.0),
        min_confidence=number("BLUE_JEV_MIN_CONFIDENCE", 0.0, 0.0, 1.0),
        priorities=os.getenv("BLUE_JEV_PRIORITIES", JevSettings.priorities)[:1000],
    )


class JevError(RuntimeError):
    pass


class FeatherlessClassifier:
    def __init__(self, settings: JevSettings, *, transport=None) -> None:
        self.settings = settings
        self.transport = transport

    def choose(self, state: dict, candidates: list[dict]) -> dict:
        cfg = load_agent_settings()
        if not cfg.api_key:
            raise JevError("credentials_unavailable")
        endpoint = "https://api.featherless.ai/v1/classifier"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.settings.timeout_s, transport=self.transport,
                              follow_redirects=False) as client:
                response = client.post(endpoint, headers=headers,
                    json={"model": self.settings.model, "state": state, "questions": {
                        "blue": {"type": "choice", "instructions":
                            "Select only one supplied candidate according to operator priorities. "
                            "Do not calculate loss or rank by the smallest loss number. "
                            "Costs, timing and capacity are unknown unless explicitly supplied.",
                            "criteria": {c["id"]: c for c in candidates}}}})
                if response.status_code >= 400:
                    raise JevError(f"http_{response.status_code}")
                answer = response.json()["answers"]["blue"]
                ids = {c["id"] for c in candidates}
                choice, confidence, probabilities = answer["choice"], answer["confidence"], answer["probabilities"]
                if answer.get("type") != "choice" or choice not in ids:
                    raise ValueError("invalid choice")
                def probability(value):
                    return (isinstance(value, (int, float)) and not isinstance(value, bool)
                            and math.isfinite(value) and 0 <= value <= 1)
                if (not probability(confidence) or not isinstance(probabilities, dict)
                        or set(probabilities) != ids or not all(probability(p) for p in probabilities.values())
                        or abs(sum(probabilities.values()) - 1) > 0.02
                        or abs(probabilities[choice] - confidence) > 0.02
                        or confidence + 1e-6 < max(probabilities.values())):
                    raise ValueError("invalid probabilities")
                return {"selected_id": choice, "confidence": confidence, "probabilities": probabilities,
                        "service_mode": "production", "model": self.settings.model,
                        "request_ms": round((time.perf_counter() - started) * 1000, 1)}
        except httpx.TimeoutException as exc:
            raise JevError("timeout") from exc
        except httpx.HTTPError as exc:
            raise JevError("transport_error") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise JevError("invalid_response") from exc


def main() -> None:
    """A small live connection check; safe to share its output, never provider error bodies."""
    import argparse

    parser = argparse.ArgumentParser(description="Check Featherless Simple Jev's classifier connection")
    parser.add_argument("--smoke", action="store_true", required=True)
    args = parser.parse_args()
    settings = load_jev_settings()
    client = FeatherlessClassifier(settings)
    started = time.perf_counter()
    try:
        result = client.choose({"operator_priorities": "Protect critical class A parts. Costs unspecified."}, [
            {"id": "c1", "action": "backup_all_affected_parts", "args": {"only_critical": True},
             "critical_parts_restored": ["A1", "A2"]},
            {"id": "c2", "action": "add_backup_supplier", "args": {"part_id": "B1"},
             "critical_parts_restored": []},
        ])
        print(json.dumps({"ok": True, **result}))
    except JevError as exc:
        print(json.dumps({"ok": False, "service_mode": "production", "reason": str(exc),
                          "request_ms": round((time.perf_counter() - started) * 1000, 1)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
