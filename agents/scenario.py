"""Scenario simulation agent: answer a natural-language disaster question by simulating it in TuringDB.

Workflow: NL question -> reasoning -> Cypher exploration -> a scenario branch (bbox/entity wipe) ->
downstream propagation -> graph diff -> explanation + map visualisation payload. The graph drives the
answer and the map; the model never invents effects it did not read from the branch. The simulation is
high-level and impact-focused — hypothetical disasters and cascading effects, not operational targeting.
"""

from __future__ import annotations

import logging

from api.refs import Ref

from agents.actions import WIPE_LABELS
from agents.branches import BranchLab
from agents.engine import Agent, StepListener, Tool, Trace
from agents.llm import FeatherlessLLM
from agents.tools import build_stacked, diff_tool, impact_tool, query_tool, schema_tool

log = logging.getLogger("agents.scenario")


SYSTEM = """You are the SCENARIO-SIMULATION agent. You answer natural-language questions about hypothetical
disasters by simulating them in the TuringDB graph, then explaining the cascading effects on infrastructure
and dependencies. This is impact analysis of hypothetical events — never operational instructions or
real-world targeting.

Place names (towns, cities) are NOT stored as a searchable field, so do not try `MATCH (:Place ...)` or
filter on a `name`/`city` property — those will fail. Instead call `places` to get the named locations with
coordinates and match the question's place to one of them.

Workflow:
1. Understand the scenario (what is destroyed, where).
2. Call `places` to turn the named place into coordinates. Then use `query` (Cypher) if you want to inspect
   the specific entities (plants, drones, suppliers) around there.
3. Use `preview_region` to confirm a bounding box contains infrastructure (plants/sites/drones) before
   committing. Centre an ~10-15 km box (about 0.1-0.15 degrees) on the matched coordinates.
4. Call `simulate_scenario` with the bounding box (and optional labels). It opens a NEW branch, destroys
   everything inside the box there (never on main), propagates downstream impact, and returns the graph
   diff plus the affected located nodes for the map.
5. Read the diff and the downstream query results. Optionally `query` the branch to trace further effects.
6. `finish` with: branch (change_id), a clear `explanation` of the effects grounded in the diff, and the
   `headline` numbers (nodes destroyed, facilities affected). The map reads your branch automatically.

Coordinates are WGS84 lat/lon. A ~10 km box is about 0.09 degrees of latitude."""


def places(lab: BranchLab) -> dict:
    """Named places in the graph with coordinates (Site.place, part-Supplier.place) — the anchors for a
    region question. Place names are NOT a queryable index, so this is how to turn 'Manchester' into a bbox."""
    s = lab.graph.session("main")
    out = []
    sites = s.q("MATCH (n:Site) RETURN n.place AS place, n.latitude AS lat, n.longitude AS lon, n.site_id AS sid")
    for place, lat, lon, sid in sites.itertuples(index=False):
        out.append({"place": str(place), "kind": "Site", "site_id": str(sid),
                    "lat": round(float(lat), 4), "lon": round(float(lon), 4)})
    sup = s.q("MATCH (n:Supplier) WHERE n.source = 'supply_chain' RETURN n.place AS place, "
              "n.latitude AS lat, n.longitude AS lon")
    for place, lat, lon in sup.dropna().itertuples(index=False):
        out.append({"place": str(place), "kind": "Supplier", "lat": round(float(lat), 4),
                    "lon": round(float(lon), 4)})
    return {"places": out, "note": "match the question's place to one of these (e.g. 'Manchester' -> the "
            "Site whose place contains Manchester); use its lat/lon as the centre of your bounding box"}


def preview_region(lab: BranchLab, west: float, south: float, east: float, north: float) -> dict:
    s = lab.graph.session("main")
    counts = {}
    for label in WIPE_LABELS:
        if label not in s.labels:
            continue
        frame = s.q(f"MATCH (n:{label}) WHERE n.latitude >= {south} AND n.latitude <= {north} "
                    f"AND n.longitude >= {west} AND n.longitude <= {east} RETURN count(n) AS c")
        c = int(frame["c"].iloc[0]) if len(frame) else 0
        if c:
            counts[label] = c
    return {"bbox": [west, south, east, north], "counts": counts, "total": sum(counts.values())}


def _affected_payload(lab: BranchLab, change_id: str, parent: str = "main") -> dict:
    """Map-ready view of the scenario branch: destroyed + downstream-affected located nodes, via /diff."""
    resp = lab.graph.backend.diff(Ref("main") if parent == "main" else Ref(str(parent)), Ref(str(change_id)))
    destroyed = [{"id": n.id, "name": n.name, "kind": n.kind, "lat": n.lat, "lon": n.lon}
                 for n in resp.removed if n.lat is not None]
    affected = [{"id": c.node.id, "name": c.node.name, "kind": c.node.kind, "lat": c.node.lat,
                 "lon": c.node.lon, "status": c.node.status} for c in resp.changed
                if c.node.lat is not None and "status" in c.fields]
    return {"destroyed": destroyed, "affected": affected, "destroyed_count": len(resp.removed),
            "affected_count": len(affected), "diff_latency_ms": resp.latency_ms}


def build_scenario_agent(lab: BranchLab, llm: FeatherlessLLM, max_steps: int = 18, parent: str = "main") -> Agent:
    def simulate_scenario(label: str, west: float, south: float, east: float, north: float,
                          labels: list[str] | None = None) -> dict:
        wipe = {"action": "wipe_bbox", "args": {"west": west, "south": south, "east": east, "north": north,
                                                "labels": labels}}
        built = build_stacked(lab, "scenario", label, parent, [wipe])  # parent = main, or a wargame head
        if "error" in built:
            return built
        payload = _affected_payload(lab, built["change_id"], parent)
        return {"branch": built["change_id"], "parent": parent, "label": label, "bbox": [west, south, east, north],
                "supply_loss_pct": built["loss_pct"], "sites_down": built["summary"]["sites_down"], **payload}

    tools = [
        query_tool(lab), schema_tool(lab),
        Tool("places", "Named places (towns/cities) in the graph with coordinates — use this to turn a "
             "place name in the question into a bounding box.", lambda: places(lab)),
        Tool("preview_region", "Count nodes by label inside a bounding box (read-only), before simulating.",
             lambda west, south, east, north: preview_region(lab, west, south, east, north),
             {"west": "min lon", "south": "min lat", "east": "max lon", "north": "max lat"}),
        Tool("simulate_scenario", "Open a new branch, destroy everything inside a bounding box there, "
             "propagate downstream impact, and return the graph diff and affected located nodes for the map.",
             simulate_scenario,
             {"label": "short scenario name", "west": "min lon", "south": "min lat", "east": "max lon",
              "north": "max lat", "labels": "optional list of labels to destroy (default all located)"}),
        diff_tool(lab), impact_tool(lab),
    ]
    return Agent("scenario", llm, SYSTEM, tools, max_steps=max_steps)


def run_scenario(lab: BranchLab, llm: FeatherlessLLM, question: str, max_steps: int = 18,
                 on_step: StepListener | None = None, parent: str = "main") -> Trace:
    """Simulate `question` on a new branch cut from `parent` (main, or a wargame head for an inject)."""
    lab.ensure_ready()
    agent = build_scenario_agent(lab, llm, max_steps, parent=parent)
    return agent.run(question, on_step)
