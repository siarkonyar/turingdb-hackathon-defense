"""TuringDB access for the agents: sessions on a ref, query timeouts, and an unattended supervisor.

The supervisor starts the server when it is down and restarts it when an agent query runs away
(TuringDB 1.37 cannot cancel a query and `turingdb stop` waits for it). After a restart the branch lab
replays its ledger, so no operator has to shut anything down or rebuild branches by hand.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable

import httpx
import pandas as pd
from turingdb import TuringDB

from api.backends.turing import TuringBackend
from api.backends.turing_session import Session
from api.refs import Ref
from api.support import Stopwatch

log = logging.getLogger("agents.runtime")
START_TIMEOUT_S = 60


class QueryTimeout(RuntimeError):
    pass


def _bin_dir() -> Path:
    import turingdb

    return Path(turingdb.__file__).resolve().parent / "bin"


class Supervisor:
    """Owns the TuringDB server process lifecycle for unattended agent runs."""

    def __init__(self, host: str, graph: str, turing_dir: Path, autostart: bool = True) -> None:
        self.host, self.graph, self.turing_dir, self.autostart = host, graph, turing_dir, autostart
        self.restarts = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []

    def on_restart(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def reachable(self, timeout: float = 3.0) -> bool:
        try:
            client = TuringDB(host=self.host)
            _set_timeout(client, timeout)
            return self.graph in client.list_available_graphs()
        except Exception:
            return False

    def ensure_running(self) -> None:
        if self.reachable():
            self._ensure_loaded()
            return
        if not self.autostart:
            raise RuntimeError(f"TuringDB is not reachable at {self.host} and AGENT_AUTOSTART=0")
        with self._lock:
            if not self.reachable():
                self._start()
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        client = TuringDB(host=self.host)
        _set_timeout(client, 120)
        client.load_graph(self.graph, raise_if_loaded=False)

    def _cli(self) -> list[str]:
        exe = _bin_dir() / "turingdb"
        return [str(exe)] if exe.exists() else ["turingdb"]

    def _start(self) -> None:
        log.warning("starting TuringDB (%s, graph %s)", self.turing_dir, self.graph)
        port = httpx.URL(self.host).port or 6666
        subprocess.run([*self._cli(), "start", "-turing-dir", str(self.turing_dir), "-demon", "-in-memory",
                        "-p", str(port), "-load", self.graph, "-start-timeout", "20000"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=START_TIMEOUT_S)
        deadline = time.time() + START_TIMEOUT_S
        while time.time() < deadline:
            if self.reachable():
                return
            time.sleep(1)
        raise RuntimeError("TuringDB did not come up")

    def _server_pids(self) -> list[int]:
        out = subprocess.run(["pgrep", "-f", f"turingdb start -turing-dir {self.turing_dir}"],
                             capture_output=True, text=True, check=False).stdout
        return [int(p) for p in out.split() if p.strip().isdigit() and int(p) != os.getpid()]

    def restart(self, reason: str) -> None:
        """Kill a wedged server and bring it back; listeners then rebuild their branches."""
        if not self.autostart:
            raise RuntimeError(f"TuringDB needs a restart ({reason}) but AGENT_AUTOSTART=0")
        with self._lock:
            log.error("restarting TuringDB: %s", reason)
            subprocess.run([*self._cli(), "stop", "-turing-dir", str(self.turing_dir), "-timeout", "2000"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            for pid in self._server_pids():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for stale in ("turingdb.lock", "turingdb.sock"):
                (self.turing_dir / stale).unlink(missing_ok=True)
            self._start()
            self.restarts += 1
        self._ensure_loaded()
        for fn in self._listeners:
            fn()


def _set_timeout(client: TuringDB, seconds: float | None) -> None:
    http = getattr(getattr(client, "impl", None), "_client", None)
    if http is not None:
        http.timeout = httpx.Timeout(seconds) if seconds else None


class Graph:
    """Sessions on refs of one graph, with a watchdog on every agent-originated query."""

    def __init__(self, host: str, graph: str, supervisor: Supervisor, timeout_s: float = 20.0) -> None:
        self.host, self.graph, self.supervisor, self.timeout_s = host, graph, supervisor, timeout_s
        self.backend = TuringBackend(host, graph)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tdb-query")

    def session(self, ref: str | Ref = "main", sw: Stopwatch | None = None) -> Session:
        r = ref if isinstance(ref, Ref) else Ref("main") if str(ref) == "main" else Ref(str(ref))
        return Session(self.host, self.graph, r, sw or Stopwatch("turingdb"))

    def new_change(self) -> str:
        client = TuringDB(host=self.host)
        client.set_graph(self.graph)
        return str(client.new_change())

    def change_ids(self) -> set[str]:
        frame = self.session("main").q("CHANGE LIST")
        return {str(c) for c in frame.iloc[:, 0]} if len(frame) else set()

    def guarded_query(self, ref: str, cypher: str) -> tuple[pd.DataFrame, float | None]:
        """Run one (already guard-checked) query with a deadline; restart the server if it hangs."""
        session = self.session(ref)
        _set_timeout(session.client, self.timeout_s + 5)
        future = self._pool.submit(session.q, cypher)
        try:
            frame = future.result(timeout=self.timeout_s)
        except FutureTimeout as exc:
            self.supervisor.restart(f"query exceeded {self.timeout_s:.0f}s: {cypher[:120]}")
            raise QueryTimeout(f"query exceeded {self.timeout_s:.0f}s and was killed; simplify it "
                               "(fewer hops, filter early, LIMIT)") from exc
        except httpx.TimeoutException as exc:
            self.supervisor.restart(f"query timed out: {cypher[:120]}")
            raise QueryTimeout("query timed out and was killed; simplify it") from exc
        return frame, session.client.get_query_exec_time()
