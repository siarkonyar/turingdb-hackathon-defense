"""Run the isolated Dover map, without touching the theatre demo or its .env.

    .venv/bin/python scripts/run_dover_demo.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datasets.dover.build import HOST, RUNTIME, generate, import_graph  # noqa: E402


def main() -> None:
    generate()
    import_graph()
    # Persist only the initial import. All subsequent scenario branches are ephemeral.
    binary = str(Path(sys.executable).parent / "turingdb")
    subprocess.run([binary, "stop", "-turing-dir", str(RUNTIME)], check=True, timeout=30)
    subprocess.run([binary, "start", "-turing-dir", str(RUNTIME), "-p", "6667", "-demon",
                    "-in-memory", "-load", "dover", "-start-timeout", "20000"], check=True, timeout=60)
    env = dict(os.environ, OPSMAP_BACKEND="turingdb", TURINGDB_HOST=HOST,
               TURINGDB_GRAPH="dover", TURINGDB_DIR=str(RUNTIME),
               OPSMAP_API_TARGET="http://127.0.0.1:8001", VITE_OPSMAP_PROFILE="dover")
    children: list[subprocess.Popen] = []
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app",
                                           "--host", "127.0.0.1", "--port", "8001"], cwd=ROOT, env=env))
        children.append(subprocess.Popen(["npm", "--prefix", "ui", "run", "dev", "--",
                                           "--host", "127.0.0.1", "--port", "5174", "--strictPort"], cwd=ROOT, env=env))
        print("Dover demo: http://127.0.0.1:5174 | graph: dover | API: 8001 | database: 6667", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        subprocess.run([binary, "stop", "-turing-dir", str(RUNTIME)], check=False, timeout=30)


if __name__ == "__main__":
    main()
