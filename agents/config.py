"""Agent runtime configuration, read from the environment.

    FEATHERLESS_API_KEY   required for model calls (environment secret; never logged)
    FEATHERLESS_BASE_URL  https://api.featherless.ai/v1
    FEATHERLESS_MODEL     pin a model; otherwise the first available entry of MODEL_PREFERENCE is used
    TURINGDB_HOST         http://localhost:6666
    TURINGDB_GRAPH        theatre
    AGENT_QUERY_TIMEOUT   seconds before an agent-written query counts as runaway (default 20)
    AGENT_AUTOSTART       1 (default): start / restart the TuringDB server without an operator

Values may also come from the gitignored `.env` at the repo root (real environment variables win).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from api.env import load_env

ROOT = Path(__file__).resolve().parents[1]

# Instruction-tuned models that follow a strict JSON action protocol well, best first. Featherless
# serves what the account's plan allows; the client takes the first one /models lists and falls back
# down this list when a call is refused.
MODEL_PREFERENCE = (
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen2.5-32B-Instruct",
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    "Qwen/Qwen2.5-14B-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
)


@dataclass(frozen=True)
class AgentSettings:
    api_key: str | None
    base_url: str
    model: str | None
    turingdb_host: str
    graph: str
    query_timeout_s: float
    autostart: bool
    turing_dir: Path


def load_agent_settings() -> AgentSettings:
    load_env()
    return AgentSettings(
        api_key=os.environ.get("FEATHERLESS_API_KEY") or None,
        base_url=os.environ.get("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1").rstrip("/"),
        model=os.environ.get("FEATHERLESS_MODEL") or None,
        turingdb_host=os.environ.get("TURINGDB_HOST", "http://localhost:6666"),
        graph=os.environ.get("TURINGDB_GRAPH", "theatre"),
        query_timeout_s=float(os.environ.get("AGENT_QUERY_TIMEOUT", "20")),
        autostart=os.environ.get("AGENT_AUTOSTART", "1") != "0",
        turing_dir=Path(os.environ.get("TURINGDB_DIR", ROOT)),
    )
