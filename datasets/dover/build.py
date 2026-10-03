"""Generate reproducible data and optionally import into a dedicated demo server.

No original graph is read, changed or stopped. Runtime artifacts live under data/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from datasets.dover.model import build_corridor
from datasets.dover.validate import validate

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data" / "dover-runtime"
HOST = "http://localhost:6667"


def generate(runtime: Path = RUNTIME) -> dict:
    c = build_corridor()
    report = validate(c)
    path = runtime / "data" / "dover.jsonl"
    c.graph.write_jsonl(path)
    report["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report["schema"] = {
        "nodes": {label: sorted({p for n in c.graph.nodes if label in n.labels for p in n.props})
                  for label in sorted(c.graph.label_counts())},
        "edges": {kind: sorted({p for e in c.graph.edges if e.edge_type == kind for p in e.props})
                  for kind in sorted(c.graph.edge_counts())},
    }
    (runtime / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "schema"}, indent=2))
    return report


def import_graph(runtime: Path = RUNTIME) -> None:
    from turingdb import TuringDB

    # Only the dedicated port and runtime are used. Never reset or delete an existing graph.
    binary = str(Path(sys.executable).parent / "turingdb")
    client = TuringDB(host=HOST)
    try:
        available = client.list_available_graphs()
    except Exception:
        subprocess.run([binary, "start", "-turing-dir", str(runtime), "-p", "6667",
                        "-demon", "-start-timeout", "20000"], check=True, timeout=60)
        client = TuringDB(host=HOST)
        available = client.list_available_graphs()
    if set(available) - {"default", "dover"}:
        raise RuntimeError("Port 6667 is serving other graphs; refusing to import into an unrelated server")
    if "dover" in available:
        client.load_graph("dover", raise_if_loaded=False)
        client.set_graph("dover")
        expected = build_corridor().graph
        # Idempotent use requires the same full export, not just equal counts.
        frame = client.query("MATCH (n:Dataset) RETURN n.schema_version AS version, "
                             "n.seed AS seed, n.build_fingerprint AS fingerprint")
        if (len(frame) != 1 or str(frame.iloc[0]["version"]) != "1.0"
                or int(frame.iloc[0]["seed"]) != 20261003
                or str(frame.iloc[0]["fingerprint"]) != expected.nodes[-1].props["build_fingerprint"]):
            raise RuntimeError("Existing dover differs; use a fresh dedicated runtime rather than replacing it")
        print("[load] existing dover retained")
    else:
        client.query("LOAD JSONL 'dover.jsonl' AS dover")
        client.set_graph("dover")
        expected = build_corridor().graph
    for label, count in expected.label_counts().items():
        actual = int(client.query(f"MATCH (n:{label}) RETURN count(n)").iloc[0, 0])
        if actual != count:
            raise RuntimeError(f"{label}: {actual} != {count}")
    for kind, count in expected.edge_counts().items():
        actual = int(client.query(f"MATCH ()-[e:{kind}]->() RETURN count(e)").iloc[0, 0])
        if actual != count:
            raise RuntimeError(f"{kind}: {actual} != {count}")
    print("[verify] all imported label and relationship counts match")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", action="store_true", help="import on dedicated localhost:6667")
    args = parser.parse_args()
    generate()
    if args.load:
        import_graph()


if __name__ == "__main__":
    main()
