"""Versioning demo on `theatre`: replay the commit history, then open a hypothesis branch
(a TuringDB change), delete a power plant, re-run the cascade query and diff it against main.
The branch is discarded at the end, so main is left untouched.

    uv run python fusion/versioning_demo.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from turingdb import TuringDB  # noqa: E402

from config import REPO_ROOT  # noqa: E402
from docblock import replace_block  # noqa: E402
from tdb import connect, count, timed_query, use_theatre  # noqa: E402

DOC = REPO_ROOT / "docs" / "theatre.md"
TARGET_PLANT = "WRI1006130"  # Wedel power station (coal, 260 MW), feeds SITE04 Hamburg-Finkenwerder

# Q1 with the plant left open: every site's power feed -> class-A parts on recent POs -> primary supplier
# -> logistics supplier -> high-risk shipments. Linear path only (multi-branch joins misbehave in 1.37).
CASCADE = """MATCH (pp:PowerPlant)<-[:POWERED_BY]-(s:Site)<-[:DELIVERED_TO]-(po:PurchaseOrder)-[:FOR_PART]->(pt:Part)-[:SUPPLIED_BY]->(sup:Supplier)-[:SOURCES_FROM]->(ls:Supplier)<-[:FROM_SUPPLIER]-(sh:Shipment)-[:CLASSIFIED_AS]->(rc:RiskClassification {name:'High Risk'})
WHERE pt.criticality_class = 'A' AND po.ts_epoch >= 1719792000
RETURN s.site_id AS site, pp.gppd_idnr AS plant, pp.name AS plant_name, pp.capacity_mw AS mw, po.po_id AS po_id, pt.part_id AS part, sup.supplier_id AS supplier, ls.supplier_id AS logistics_supplier, sh.shipment_id AS shipment"""
FEEDS = """MATCH (pp:PowerPlant)<-[e:POWERED_BY]-(s:Site)
RETURN s.site_id AS site, pp.gppd_idnr AS plant, pp.name AS plant_name, pp.primary_fuel AS fuel, pp.capacity_mw AS mw"""


@dataclass(frozen=True)
class Snapshot:
    cascade: pd.DataFrame
    feeds: pd.DataFrame
    cascade_ms: float
    nodes: int
    edges: int


def snapshot(client: TuringDB) -> Snapshot:
    cascade = timed_query(client, CASCADE)
    return Snapshot(cascade.frame, client.query(FEEDS), cascade.server_ms,
                    count(client, "MATCH (n) RETURN count(n)"), count(client, "MATCH (a)-[e]->(b) RETURN count(e)"))


def replay_history(client: TuringDB) -> pd.DataFrame:
    history = client.query("CALL db.history()")
    rows = []
    for commit, nodes, edges in history[["commit", "nodeCount", "edgeCount"]].itertuples(index=False):
        commit_hash = commit.replace("(HEAD)", "")
        client.set_commit(commit_hash)
        labels = set(client.query("CALL db.labels()")["label"])
        reports = count(client, "MATCH (r:Report) RETURN count(r)") if "Report" in labels else 0
        total = count(client, "MATCH (n) RETURN count(n)") if labels else 0
        rows.append({"commit": commit_hash, "nodes_added": nodes, "edges_added": edges,
                     "total_nodes": total, "reports": reports})
    client.checkout()
    return pd.DataFrame(rows[::-1])  # oldest first


def diff_rows(main: pd.DataFrame, branch: pd.DataFrame) -> pd.DataFrame:
    """Multiset row diff: side = 'main_only' | 'branch_only'."""
    keyed = [df.assign(_n=df.groupby(list(df.columns)).cumcount()) for df in (main, branch)]
    merged = keyed[0].merge(keyed[1], how="outer", indicator=True)
    merged = merged[merged["_merge"] != "both"].drop(columns="_n")
    return merged.assign(side=merged.pop("_merge").map({"left_only": "main_only", "right_only": "branch_only"}))


def run_branch(client: TuringDB) -> tuple[Snapshot, Snapshot, int]:
    main = snapshot(client)
    change = client.new_change()
    client.checkout(change=change)
    client.query(f"MATCH (p:PowerPlant {{gppd_idnr:'{TARGET_PLANT}'}}) DETACH DELETE p")
    client.query("COMMIT")  # make the delete visible inside the change
    branch = snapshot(client)
    client.query("CHANGE DELETE")  # discard the hypothesis branch
    client.checkout()
    return main, branch, change


def site_summary(main: Snapshot, branch: Snapshot) -> pd.DataFrame:
    def per_site(s: Snapshot, tag: str) -> pd.DataFrame:
        feeds = s.feeds.groupby("site").agg(**{f"feeds_{tag}": ("plant", "size"), f"mw_{tag}": ("mw", "sum")})
        rows = s.cascade.groupby("site").size().rename(f"cascade_rows_{tag}")
        return feeds.join(rows)
    out = per_site(main, "main").join(per_site(branch, "branch")).fillna(0).reset_index()
    return out.astype({c: int for c in out.columns if c.startswith(("feeds", "cascade"))}).round(1)


def report_markdown(history: pd.DataFrame, main: Snapshot, branch: Snapshot, change: int,
                    diff: pd.DataFrame) -> str:
    removed = diff[diff.side == "main_only"]
    plant_name = main.feeds.loc[main.feeds.plant == TARGET_PLANT, "plant_name"].iloc[0]
    parts_main = set(main.cascade.loc[main.cascade.site == "SITE04", "part"])
    parts_branch = set(branch.cascade.loc[branch.cascade.site == "SITE04", "part"])
    lines = [
        "**1. Replay the history** (`client.set_commit(<hash>)` on each commit of `CALL db.history()`):", "",
        history.to_markdown(index=False), "",
        f"**2. Branch.** `client.new_change()` opened change `{change}`; inside it "
        f"`MATCH (p:PowerPlant {{gppd_idnr:'{TARGET_PLANT}'}}) DETACH DELETE p` then `COMMIT` "
        f"(removes {plant_name} and its incident edges).", "",
        "| | main | branch |", "|---|--:|--:|",
        f"| nodes | {main.nodes:,} | {branch.nodes:,} |",
        f"| edges | {main.edges:,} | {branch.edges:,} |",
        f"| cascade rows | {len(main.cascade):,} | {len(branch.cascade):,} |",
        f"| cascade latency (ms) | {main.cascade_ms:.1f} | {branch.cascade_ms:.1f} |", "",
        "**3. Diff of the cascade query, per site** (feeds = `POWERED_BY` plants, mw = their summed capacity):", "",
        site_summary(main, branch).to_markdown(index=False), "",
        f"Row diff: {len(removed):,} rows exist only on main, {int((diff.side == 'branch_only').sum())} only on "
        f"the branch. Every removed row runs through `{TARGET_PLANT}`: "
        f"{sorted(removed.plant.unique().tolist())}, all at {sorted(removed.site.unique().tolist())}.", "",
        f"Reading: SITE04 keeps {len(parts_branch)}/{len(parts_main)} of its class-A parts reachable "
        f"through its remaining feeds, but its feed capacity drops from "
        f"{main.feeds.loc[main.feeds.site == 'SITE04', 'mw'].sum():.0f} MW to "
        f"{branch.feeds.loc[branch.feeds.site == 'SITE04', 'mw'].sum():.0f} MW. No other site changes.", "",
        "**4. Discard.** `CHANGE DELETE` drops the branch; main still has "
        f"{main.nodes:,} nodes / {main.edges:,} edges.",
    ]
    return "\n".join(lines)


def main() -> None:
    client = connect()
    use_theatre(client)
    history = replay_history(client)
    print(history.to_string(index=False))
    main_snap, branch_snap, change = run_branch(client)
    after = count(client, "MATCH (n) RETURN count(n)")
    if after != main_snap.nodes:
        raise RuntimeError(f"main changed after discarding the branch: {after} != {main_snap.nodes}")
    diff = diff_rows(main_snap.cascade, branch_snap.cascade)
    print(site_summary(main_snap, branch_snap).to_string(index=False))
    print(f"diff: {(diff.side == 'main_only').sum()} main-only rows, {(diff.side == 'branch_only').sum()} "
          f"branch-only rows; main intact ({after:,} nodes)")
    replace_block(DOC, "VERSIONING_DEMO", report_markdown(history, main_snap, branch_snap, change, diff))
    print(f"[doc] updated VERSIONING_DEMO block in {DOC.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
