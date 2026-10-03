"""Readable match scripts for reviewing a recording without the graph or a model connection."""

from __future__ import annotations

import json


def transcript(data: dict) -> str:
    summary = data.get("summary", {})
    lines = [f"# Wargame {data.get('id', 'unknown')}", "",
             f"Created: {data.get('created', 'unknown')}",
             f"Status: {data.get('status', 'unknown')}",
             f"Model: {data.get('model') or 'unavailable'}",
             f"Base branch: {data.get('base_branch', 'main')}",
             f"Base loss: {data.get('base_loss_pct', 0)}%",
             f"Rounds: {data.get('rounds', 0)}",
             f"Final loss vs base: {summary.get('final_loss_pct', 'unknown')} percentage points", "",
             "Scores use gameplay assumptions; they are not calibrated production forecasts.", ""]
    if data.get("base_actions"):
        lines += ["## Base scenario", "", "```json", json.dumps(data["base_actions"], indent=2), "```", ""]
    if summary.get("strategic"):
        lines += [f"Cumulative loss: {summary.get('cumulative_loss')} percentage-point rounds",
                  f"Average loss: {summary.get('average_loss_pct')}%",
                  f"Priority objectives held: {summary.get('objective_met')}", ""]
    for index, move in enumerate(data.get("moves", []), 1):
        lines += [f"## {index}. Round {move.get('round', '?')} · {move.get('side', '?').upper()}", "",
                  str(move.get("label", move.get("action", "Move"))), "",
                  f"Rationale: {move.get('rationale') or 'No rationale recorded.'}", "",
                  "```json", json.dumps(move.get("actions", []), indent=2), "```", "",
                  f"Loss: {move.get('abs_loss_pct', '?')}% total; {move.get('loss_pct', '?')} points vs base"]
        split = move.get("breakdown") or {}
        if split:
            lines.append(f"Deep network: {split.get('deep_pct')}%; parts layer: {split.get('legacy_pct')}%")
        strategy = move.get("strategy") or {}
        if strategy:
            lines += ["Exercise state and compared plans:", "```json", json.dumps(strategy, indent=2), "```"]
        lines += [f"Branch: {move.get('parent_id', '?')} → {move.get('branch_id', '?')}",
                  f"Timing: LLM {move.get('llm_ms', 0)} ms; DB {move.get('db_ms', 0)} ms",
                  f"Fallback: {'yes' if move.get('fallback') else 'no'}"]
        targets = move.get("targets", [])
        if targets:
            lines.append("Map targets: " + "; ".join(
                f"{t.get('name', t.get('id'))} ({t.get('kind')}, {t.get('lat')}, {t.get('lon')})" for t in targets))
        lines += [f"Map arcs: {len(move.get('arcs', []))}", ""]
    errors = [e.get("data", {}).get("message", "Unknown error") for e in data.get("events", [])
              if e.get("type") == "error"]
    if errors:
        lines += ["## Errors", "", *errors, ""]
    return "\n".join(lines)
