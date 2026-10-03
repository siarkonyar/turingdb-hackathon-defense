"""Scenario simulation agent: answer a natural-language disaster question by simulating it in TuringDB.

Workflow: NL question -> reasoning -> Cypher exploration -> a scenario branch (bbox/entity wipe) ->
downstream propagation -> graph diff -> explanation + map visualisation payload. The graph drives the
answer and the map; the model never invents effects it did not read from the branch. The simulation is
high-level and impact-focused — hypothetical disasters and cascading effects, not operational targeting.
"""

from __future__ import annotations

import logging
from collections import Counter

from api.refs import Ref

from agents.actions import WIPE_DEFAULT as WIPE_LABELS, apply_action
from agents.branches import BranchLab
from agents.engine import Agent, Tool, Trace
from agents.llm import FeatherlessLLM
from agents.tools import diff_tool, impact_tool, query_tool, schema_tool

log = logging.getLogger("agents.scenario")

LIST_CAP = 25  # items per list in a tool observation (counts stay complete)

SYSTEM = """You are the SCENARIO-SIMULATION agent. You answer natural-language questions about hypothetical
disasters by simulating them in the TuringDB graph, then explaining the cascading effects on infrastructure
and dependencies. This is impact analysis of hypothetical events — never operational instructions or
real-world targeting.

The graph holds two supply layers: the original one (Sites, part Suppliers, Parts) and the deep defence
supply network (Facility mine -> refinery -> ... -> final assembly plant, linked by SUPPLIES; Platform /
Component / Material items; Port, Chokepoint, Company). Consider BOTH, plus power plants, drones and the
local population data (Locations, Crimes, People), when explaining effects. Deep facilities draw power from
nearby plants (POWERED_BY), so a regional event can hit a facility directly or by cutting its power.

Place names (towns, cities) are NOT stored as a searchable field, so do not try `MATCH (:Place ...)` or
filter on a `name`/`city` property — those will fail. Instead call `places` to get the named locations with
coordinates and match the question's place to one of them.

Workflow:
1. Understand the scenario (what is destroyed, where).
2. Call `places` with {"name": "<place>"} to turn the named place into coordinates (it lists sites, suppliers, deep-facility cities
   and ports). Then use `query` (Cypher) if you want to inspect the specific entities around there.
3. Use `preview_region` to confirm a bounding box contains infrastructure (plants/sites/drones) before
   committing. Centre an ~10-15 km box (about 0.1-0.15 degrees) on the matched coordinates.
4. Call `simulate_scenario` with the bounding box (and optional labels). It opens a NEW branch, destroys
   everything inside the box there (never on main), propagates downstream impact, and returns the graph
   diff plus the affected located nodes for the map.
5. Read the diff and the downstream query results. Optionally `query` the branch to trace further effects.
6. `finish` with: branch (change_id), a clear `explanation` of the effects grounded in the diff, and the
   `headline` numbers (nodes destroyed, facilities affected, platforms affected). Use the `deep_supply`
   section of the simulation result to explain the knock-on effects in the deep supply network. The map reads your branch automatically.

Coordinates are WGS84 lat/lon. A ~10 km box is about 0.09 degrees of latitude."""


def places(lab: BranchLab, name: str | None = None) -> dict:
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
    fac = s.q("MATCH (n:Facility) RETURN n.city AS city, n.country_code AS cc, avg(n.latitude) AS lat, "
              "avg(n.longitude) AS lon, count(n) AS facilities")
    for city, cc, lat, lon, n in fac.dropna().itertuples(index=False):
        out.append({"place": f"{city} ({cc})", "kind": "deep Facility city", "facilities": int(n),
                    "lat": round(float(lat), 4), "lon": round(float(lon), 4)})
    ports = s.q("MATCH (n:Port) RETURN n.name AS place, n.latitude AS lat, n.longitude AS lon")
    for place, lat, lon in ports.dropna().itertuples(index=False):
        out.append({"place": str(place), "kind": "Port", "lat": round(float(lat), 4), "lon": round(float(lon), 4)})
    if name:  # case-insensitive substring filter keeps the observation small
        want = name.strip().lower()
        hits = [p for p in out if want in p["place"].lower()]
        out = hits or [{"note": f"no place matches {name!r}; call places without a name for the full list "
                                "(or use known coordinates)"}]
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


def _affected_payload(lab: BranchLab, change_id: str) -> dict:
    """Map-ready view of the scenario branch: destroyed + downstream-affected located nodes, via /diff.
    Lists are capped for the model; the counts by kind are complete."""
    resp = lab.graph.backend.diff(Ref("main"), Ref(str(change_id)))
    destroyed = [n for n in resp.removed if n.lat is not None]
    affected = [c.node for c in resp.changed if c.node.lat is not None and "status" in c.fields]
    by_kind = lambda nodes: dict(Counter(n.kind for n in nodes))  # noqa: E731
    return {"destroyed_by_kind": by_kind(destroyed), "affected_by_kind": by_kind(affected),
            "destroyed": [{"name": n.name, "kind": n.kind} for n in destroyed[:LIST_CAP]],
            "affected": [{"name": n.name, "kind": n.kind, "status": n.status} for n in affected[:LIST_CAP]],
            "destroyed_count": len(resp.removed), "affected_count": len(affected),
            "diff_latency_ms": resp.latency_ms}


def deep_supply(lab: BranchLab, change_id: str) -> dict:
    """Knock-on effects in the supply_chain_deep network: facilities destroyed or flagged on the branch, every
    facility downstream of them on main (SUPPLIES, any depth), and the platforms built at an affected site."""
    main, br = lab.graph.session("main"), lab.graph.session(str(change_id))
    if "Facility" not in main.labels:
        return {}
    keys = dict(main.q("MATCH (f:Facility) RETURN f, f.facility_id AS k").astype(str).itertuples(index=False))
    alive = {str(x) for x in br.q("MATCH (f:Facility) RETURN f")["f"]}
    flagged = {str(x) for x in br.q("MATCH (f:Facility) WHERE f.ops_status IS NOT NULL RETURN f")["f"]} \
        if "ops_status" in br.property_types else set()
    destroyed = set(keys) - alive
    hit = destroyed | flagged
    buyers: dict[str, set[str]] = {}
    for a, b in main.q("MATCH (a:Facility)-[:SUPPLIES]->(b:Facility) RETURN a, b").astype(str).itertuples(index=False):
        buyers.setdefault(a, set()).add(b)
    downstream, frontier = set(), set(hit)
    while frontier:  # breadth-first over the supplier network, any number of tiers
        frontier = {b for f in frontier for b in buyers.get(f, ())} - downstream - hit
        downstream |= frontier
    plats = main.q("MATCH (p:Platform)-[:PRODUCED_AT]->(f:Facility) RETURN p.name AS name, f").astype(str)
    direct = sorted({n for n, f in plats.itertuples(index=False) if f in hit})
    exposed = sorted({n for n, f in plats.itertuples(index=False) if f in downstream})
    return {"facilities_destroyed": len(destroyed), "facilities_flagged": len(flagged),
            "facilities_downstream": len(downstream),
            "example_destroyed": sorted(keys[f] for f in destroyed)[:10],
            "platforms_built_at_hit_facility": direct, "platforms_downstream": exposed[:LIST_CAP],
            "platforms_downstream_count": len(exposed)}


def build_scenario_agent(lab: BranchLab, llm: FeatherlessLLM, max_steps: int = 18) -> Agent:
    def simulate_scenario(label: str, west: float, south: float, east: float, north: float,
                          labels: list[str] | None = None) -> dict:
        spec = {"actions": [
            {"action": "wipe_bbox", "args": {"west": west, "south": south, "east": east, "north": north,
                                             "labels": labels}},
            {"action": "propagate", "args": {}},
        ], "question_region": [west, south, east, north]}
        s, rec = lab.open_branch("scenario", label, spec)
        for step in spec["actions"]:
            apply_action(lab, s, step["action"], step.get("args", {}))
        imp = lab.evaluate_branch(rec.change_id)
        payload = _affected_payload(lab, rec.change_id)
        return {"branch": rec.change_id, "label": label, "bbox": [west, south, east, north],
                "original_layer_supply_loss_pct": round(100 * imp.loss, 1), "sites_down": imp.sites_down,
                "deep_supply": deep_supply(lab, rec.change_id), **payload}

    tools = [
        query_tool(lab), schema_tool(lab),
        Tool("places", "Named places (sites, supplier towns, deep-facility cities, ports) with coordinates — "
             "use this to turn a place name in the question into a bounding box.",
             lambda name=None: places(lab, name),
             {"name": "optional place name to search for, e.g. 'Manchester' (recommended)"}),
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


def run_scenario(lab: BranchLab, llm: FeatherlessLLM, question: str, max_steps: int = 18) -> Trace:
    lab.ensure_ready()
    agent = build_scenario_agent(lab, llm, max_steps)
    return agent.run(question)
