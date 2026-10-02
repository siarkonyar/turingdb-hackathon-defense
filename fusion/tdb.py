"""TuringDB server lifecycle and query helpers shared by the build, query runner and demo."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from turingdb import TuringDB

from config import GRAPH_NAME, REPO_ROOT, SERVER_URL, SOURCES, graphs_dir

START_TIMEOUT_S = "60"


def _turingdb_bin() -> str:
    candidate = Path(sys.executable).parent / "turingdb"
    return str(candidate) if candidate.exists() else "turingdb"


def _run_cli(*args: str, check: bool = True) -> None:
    """Run the turingdb CLI quietly; show its output only if it fails."""
    proc = subprocess.run([_turingdb_bin(), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"turingdb {' '.join(args[:1])} failed:\n{proc.stdout}\n{proc.stderr}")


def _server_up() -> bool:
    try:
        TuringDB(host=SERVER_URL).list_loaded_graphs()
        return True
    except Exception:  # connection refused etc. -- any failure means "not usable"
        return False


def start_server() -> None:
    print(f"[tdb] starting TuringDB server on {REPO_ROOT}")
    _run_cli("start", "-turing-dir", str(REPO_ROOT), "-demon", "-start-timeout", START_TIMEOUT_S)
    for _ in range(60):
        if _server_up():
            return
        time.sleep(1)
    raise RuntimeError(f"TuringDB did not come up at {SERVER_URL}")


def stop_server() -> None:
    print("[tdb] stopping TuringDB server")
    _run_cli("stop", "-turing-dir", str(REPO_ROOT), check=False)
    for _ in range(30):
        if not _server_up():
            return
        time.sleep(1)
    raise RuntimeError("TuringDB server did not stop")


def connect() -> TuringDB:
    if not _server_up():
        start_server()
    return TuringDB(host=SERVER_URL)


def reset_theatre(client: TuringDB) -> TuringDB:
    """Remove any previous theatre graph. TuringDB has no DROP GRAPH, so a loaded graph
    requires a server restart before its directory can be deleted."""
    target = graphs_dir() / GRAPH_NAME
    if target.parent != graphs_dir() or target.name != GRAPH_NAME:
        raise RuntimeError(f"refusing to delete unexpected path {target}")
    loaded = GRAPH_NAME in client.list_loaded_graphs()
    if loaded:
        stop_server()
    if target.exists():
        print(f"[tdb] removing previous {target}")
        shutil.rmtree(target)
    if loaded:
        start_server()
        client = TuringDB(host=SERVER_URL)
        if GRAPH_NAME in client.list_loaded_graphs():
            raise RuntimeError("theatre still loaded after restart: is another server on this port?")
    return client


def load_sources(client: TuringDB) -> None:
    for graph in SOURCES:
        client.load_graph(graph, raise_if_loaded=False)


def use_theatre(client: TuringDB) -> None:
    client.load_graph(GRAPH_NAME, raise_if_loaded=False)
    client.set_graph(GRAPH_NAME)
    client.checkout()


@dataclass(frozen=True)
class TimedResult:
    frame: pd.DataFrame
    server_ms: float | None
    total_ms: float | None


def timed_query(client: TuringDB, cypher: str) -> TimedResult:
    frame = client.query(cypher)
    return TimedResult(frame, client.get_query_exec_time(), client.get_total_exec_time())


def count(client: TuringDB, cypher: str) -> int:
    return int(client.query(cypher).iloc[0, 0])
