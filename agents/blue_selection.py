"""Shared bounded Blue proposal/choice boundary. Only locally validated actions can leave it."""
from __future__ import annotations

import copy
import json
import time
from typing import Callable

from agents.jev import FeatherlessClassifier, JevSettings, load_jev_settings
from agents.llm import parse_action

CAP = 5
LEGACY_BLUE = {"backup_all_affected_parts", "add_backup_supplier", "reroute_supplier",
               "restore_power", "prioritise_air_defence"}


class BlueSelector:
    def __init__(self, settings: JevSettings | None = None, classifier=None) -> None:
        self.settings = settings or load_jev_settings()
        self.classifier = classifier or FeatherlessClassifier(self.settings)

    def select(self, llm, state: dict, validate: Callable[[dict], dict | None],
               offered: list[dict] | None = None) -> tuple[dict | None, dict]:
        audit = {"selector": "existing_blue", "fallback": False, "candidates": [],
                 "selected_id": None, "llm_calls": 0, "jev_calls": 0, "request_ms": 0.0,
                 "proposal_ms": 0.0, "confidence": None, "service_mode": "production"}
        if not self.settings.enabled:
            return None, audit
        started = time.perf_counter()
        try:
            pool = []
            # Keep different intervention kinds visible instead of filling the cap with one kind.
            if offered is not None:
                for c in offered:
                    if not any(p["action"] == c["action"] for p in pool):
                        pool.append(copy.deepcopy(c))
                pool = (pool + [copy.deepcopy(c) for c in offered if c not in pool])[:CAP]
                for i, c in enumerate(pool):
                    c["id"] = f"c{i + 1}"
            prompt = ("Propose 3 to 5 distinct defensive candidates, one action each. Return JSON "
                      '{"action":"propose","args":{"candidates":[...]}}. '
                      "When offered candidates exist, return only their IDs; otherwise each candidate is "
                      "{action,args} using these contracts: backup_all_affected_parts{only_critical?:bool}, "
                      "add_backup_supplier{part_id}, reroute_supplier{supplier_id}, restore_power{facility_id}, "
                      "prioritise_air_defence{gppd_idnr}. Use only known identifiers. No costs or timing guesses.")
            audit["llm_calls"] = 1
            try:
                reply = llm.chat([{"role": "system", "content": prompt}, {"role": "user", "content":
                    json.dumps({"state": state, "operator_priorities": self.settings.priorities,
                                "offered": pool}, default=str)}], agent="blue_candidates", max_tokens=700, bounded=True)
            finally:
                audit["proposal_ms"] = round((time.perf_counter() - started) * 1000, 1)
            proposals = parse_action(reply)["args"].get("candidates")
            if not isinstance(proposals, list) or not 2 <= len(proposals) <= CAP:
                raise ValueError("invalid_candidates")
            candidates = []
            for p in proposals:
                if pool:
                    cid = p if isinstance(p, str) else p.get("id") if isinstance(p, dict) else None
                    candidate = next((c for c in pool if c["id"] == cid), None)
                else:
                    candidate = p if isinstance(p, dict) and p.get("action") in LEGACY_BLUE else None
                if candidate is None or not isinstance(candidate.get("args", {}), dict):
                    continue
                if offered is None and not _legacy_contract(candidate):
                    continue
                step = {"action": candidate["action"], "args": copy.deepcopy(candidate.get("args", {}))}
                if any(c["action"] == step["action"] and c["args"] == step["args"] for c in candidates):
                    continue
                evidence = validate(step)
                if evidence is not None:
                    candidates.append({**step, **evidence, "id": f"c{len(candidates) + 1}"})
            audit["candidates"] = copy.deepcopy(candidates)
            if len(candidates) < 2:
                raise ValueError("insufficient_valid_candidates")
            # Measured outcomes stay in the audit; Jev judges priorities and coverage, not loss numbers.
            criteria = [{k: v for k, v in c.items() if k not in ("loss_pct", "planning", "est_reduction_pct")}
                        for c in candidates]
            audit["jev_calls"] = 1
            request_start = time.perf_counter()
            try:
                result = self.classifier.choose(_without_loss({**state, "operator_priorities": self.settings.priorities}), criteria)
            finally:
                audit["request_ms"] = round((time.perf_counter() - request_start) * 1000, 1)
            audit.update(result)
            chosen = next((c for c in candidates if c["id"] == result["selected_id"]), None)
            if chosen is None:
                raise ValueError("invalid_candidate_id")
            if result["confidence"] < self.settings.min_confidence:
                raise ValueError("below_threshold")
            audit["selector"] = "jev"
            audit["selected_candidate"] = copy.deepcopy(chosen)
            return {"action": chosen["action"], "args": copy.deepcopy(chosen["args"])}, audit
        except Exception as exc:
            # Safe diagnostic codes only: never include provider text, prompts or headers.
            from agents.jev import JevError
            audit.update(fallback=True, reason=str(exc) if isinstance(exc, JevError) else type(exc).__name__)
            return None, audit

    def explain(self, llm, audit: dict, outcome: dict) -> str:
        audit["llm_calls"] += 1
        try:
            reply = llm.chat([{"role": "system", "content":
                'Explain the executed Blue decision in one sentence. Return {"action":"finish",'
                '"args":{"explanation":"..."}}. Outcomes are Python graph measurements. '
                "Jev selects an option; it does not write explanations or guarantee correctness."},
                {"role": "user", "content": json.dumps({"decision": audit, "outcome": outcome}, default=str)}],
                agent="blue_explanation", max_tokens=250, bounded=True)
            return str(parse_action(reply)["args"]["explanation"])[:500]
        except Exception:
            audit["explanation_fallback"] = True
            return "Selected defensive measure executed; outcome measured on its graph branch."


def _without_loss(value):
    """Keep Python loss estimates out of the priority classifier's context."""
    if isinstance(value, dict):
        return {k: _without_loss(v) for k, v in value.items()
                if "loss" not in k.lower() and k not in ("planning", "history")}
    if isinstance(value, list):
        return [_without_loss(v) for v in value]
    return value


def _legacy_contract(candidate: dict) -> bool:
    """Use the canonical argument forms advertised to the proposal model."""
    args = candidate.get("args", {})
    if candidate["action"] == "backup_all_affected_parts":
        return set(args) <= {"only_critical"} and isinstance(args.get("only_critical", False), bool)
    key = {"add_backup_supplier": "part_id", "reroute_supplier": "supplier_id",
           "restore_power": "facility_id", "prioritise_air_defence": "gppd_idnr"}[candidate["action"]]
    return set(args) == {key} and isinstance(args[key], str) and bool(args[key].strip())
