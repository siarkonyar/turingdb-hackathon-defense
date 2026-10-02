"""Rebuild the fused `theatre` graph from scratch.

    uv run python fusion/build_theatre.py

Reads the six bundled graphs (never writes to them), fuses them with real joins and seeded
synthetic bridges, loads the result as a new TuringDB graph (commit 1), then commits the
intelligence reports in batches so the history can be replayed and diffed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from turingdb import TuringDB  # noqa: E402

import config as cfg  # noqa: E402
from assemble import assemble_base  # noqa: E402
from extract import export_graph  # noqa: E402
from graph_model import GraphBuilder  # noqa: E402
from links import add_synthetic_links  # noqa: E402
from reports import commit_report_batches  # noqa: E402
from tdb import connect, count, load_sources, reset_theatre, use_theatre  # noqa: E402

EXPECTED_TYPES = {"lead_time_days": "Double", "timestamp": "String", "ts_epoch": "Int64", "timestep": "Int64",
                  "synthetic": "Bool", "latitude": "Double", "distance_km": "Double", "source": "String"}


def build_graph() -> GraphBuilder:
    client = connect()
    load_sources(client)
    sources = {g: export_graph(client, g) for g in cfg.SOURCES}
    for g, s in sources.items():
        print(f"[extract] {g}: {s.node_total():,} nodes, {s.edge_total():,} edges")
    rng = np.random.default_rng(cfg.SEED)
    asm = assemble_base(sources, rng)
    add_synthetic_links(asm, rng)
    return asm.builder


def load_graph(client: TuringDB, builder: GraphBuilder) -> TuringDB:
    path = cfg.data_dir() / cfg.JSONL_NAME
    builder.write_jsonl(path)
    print(f"[load] wrote {path.relative_to(cfg.REPO_ROOT)} ({path.stat().st_size / 1e6:.0f} MB)")
    client = reset_theatre(client)
    start = time.time()
    client.query(f"LOAD JSONL '{cfg.JSONL_NAME}' AS {cfg.GRAPH_NAME}")
    print(f"[load] LOAD JSONL -> {cfg.GRAPH_NAME} in {time.time() - start:.1f}s")
    use_theatre(client)
    return client


def verify(client: TuringDB, builder: GraphBuilder) -> None:
    bad = []
    for label, expected in sorted(builder.label_counts().items()):
        got = count(client, f"MATCH (n:{label}) RETURN count(n)")
        if got != expected:
            bad.append(f"node {label}: {got} != {expected}")
    for etype, expected in sorted(builder.edge_counts().items()):
        got = count(client, f"MATCH (a)-[e:{etype}]->(b) RETURN count(e)")
        if got != expected:
            bad.append(f"edge {etype}: {got} != {expected}")
    types = dict(client.query("CALL db.propertyTypes()")[["propertyType", "valueType"]].itertuples(index=False))
    bad += [f"type {p}: {types.get(p)} != {t}" for p, t in EXPECTED_TYPES.items() if types.get(p) != t]
    if bad:
        raise RuntimeError("theatre verification failed:\n  " + "\n  ".join(bad))
    print(f"[verify] {len(builder.label_counts())} labels, {len(builder.edge_counts())} edge types and "
          f"{len(EXPECTED_TYPES)} property types match the build ({len(builder.nodes):,} nodes, "
          f"{len(builder.edges):,} edges)")


def main() -> None:
    started = time.time()
    builder = build_graph()
    client = load_graph(connect(), builder)
    verify(client, builder)
    commit_report_batches(client)
    print(client.query("CALL db.history()").to_string(index=False))
    print(f"[done] theatre rebuilt in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
