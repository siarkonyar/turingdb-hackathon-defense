"""Shared fixtures for live agent tests. The whole live module is skipped unless BOTH a TuringDB server
with the theatre graph AND the Featherless API key are available, so the suite stays green offline."""

from __future__ import annotations

import os

import pytest

from agents.config import load_agent_settings

HOST = os.environ.get("TURINGDB_HOST", "http://localhost:6666")
GRAPH = os.environ.get("TURINGDB_GRAPH", "theatre")


def turingdb_reachable() -> bool:
    try:
        from turingdb import TuringDB

        return GRAPH in TuringDB(host=HOST).list_available_graphs()
    except Exception:
        return False


def featherless_available() -> bool:
    cfg = load_agent_settings()
    if not cfg.api_key:
        return False
    try:
        from agents.llm import FeatherlessLLM

        return bool(FeatherlessLLM(cfg).available_models())
    except Exception:
        return False


@pytest.fixture(scope="session")
def lab():
    from agents.branches import BranchLab
    from agents.runtime import Graph, Supervisor

    cfg = load_agent_settings()
    sup = Supervisor(cfg.turingdb_host, cfg.graph, cfg.turing_dir, autostart=cfg.autostart)
    sup.ensure_running()
    graph = Graph(cfg.turingdb_host, cfg.graph, sup, timeout_s=cfg.query_timeout_s)
    branch_lab = BranchLab(graph)
    branch_lab.ensure_ready()
    yield branch_lab
    for rec in branch_lab.records():  # tests keep branches for comparison; clean up at the end
        try:
            branch_lab.discard(rec.change_id)
        except Exception:
            pass


@pytest.fixture(scope="session")
def llm():
    from agents.llm import FeatherlessLLM

    return FeatherlessLLM(load_agent_settings())
