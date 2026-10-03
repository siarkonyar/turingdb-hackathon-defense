"""The live wargame board: every match move is a TuringDB branch built by the BranchLab.

TuringDB 1.37 cannot open a change on top of a change, so a move "stacked on the head" is a fresh change cut
from main that replays the head's lineage and then the new action (build_stacked). The map payload of a move
(targets to flash, cascade arcs) comes from the OpsMap node diff between the parent and the new branch.
"""

from __future__ import annotations

import logging
from typing import Any

from api.backends.turing_session import first_label, id_clauses
from api.models import Node
from api.refs import Ref

from agents.actions import _resolve_facility
from agents.branches import BranchLab
from agents.guard import UnsafeQuery, check_read_query
from agents.match import InjectResult, MoveRejected
from agents.scenario import run_scenario
from agents.threat import scout_targets
from agents.tools import PROPAGATE, build_stacked, lineage_actions

log = logging.getLogger("agents.match_board")

ROLE = {"red": "threat", "blue": "defence", "inject": "scenario"}
TARGET_CAP = 40
AFFECTED_CAP = 120
QUERY_ROWS = 20
INJECT_STEPS = 6  # places -> (preview) -> simulate -> finish, with room for one retry
# action arg -> (label, key property) used to find the node a move names; None = Site or Supplier
KEY_ARGS = (("supplier_id", "Supplier", "supplier_id"), ("site_id", "Site", "site_id"),
            ("facility_id", None, None), ("gppd_idnr", "PowerPlant", "gppd_idnr"))
KIND = {"PowerPlant": "plant", "Site": "site", "Supplier": "supplier", "Drone": "drone"}
SEVERITY = {None: 0, "at_risk": 1, "no_power": 2, "lost": 3}


def _ref(branch: str) -> Ref:
    return Ref("main") if str(branch) == "main" else Ref(str(branch))


def _located(n: Node) -> bool:
    return n.lat is not None and n.lon is not None


def _point(n: Node) -> dict:
    return {"id": n.id, "name": n.name, "kind": n.kind, "lat": n.lat, "lon": n.lon, "status": n.status}


def _severity_moved(change, up: bool) -> bool:
    if "status" not in change.fields:
        return False
    before, after = (SEVERITY.get(v, 0) for v in change.fields["status"])
    return after > before if up else after < before


class LabBoard:
    def __init__(self, lab: BranchLab) -> None:
        self.lab = lab

    # ------------------------------------------------------------------ state

    def loss(self, branch: str) -> float:
        if str(branch) == "main":
            return self.lab.baseline.loss
        rec = self.lab.record(str(branch))
        if rec is not None and rec.loss is not None:
            return rec.loss
        return self.lab.evaluate_branch(str(branch)).loss

    def lineage(self, branch: str) -> list[dict]:
        return lineage_actions(self.lab, str(branch))

    def stack(self, side: str, label: str, parent: str, actions: list[dict]) -> str:
        built = build_stacked(self.lab, ROLE[side], label, str(parent), actions)
        if "error" in built:
            raise MoveRejected(built["error"])
        return str(built["change_id"])

    def rebuild(self, label: str, actions: list[dict]) -> str:
        """Recreate a base branch (main + actions) for a replay; an empty lineage is just main."""
        edits = [a for a in actions if a.get("action") != PROPAGATE["action"]]
        return self.stack("inject", label, "main", edits) if edits else "main"

    def query(self, branch: str, cypher: str) -> dict:
        try:
            safe = check_read_query(cypher)
        except UnsafeQuery as exc:
            return {"error": str(exc)}
        frame, ms = self.lab.graph.guarded_query(str(branch), safe)
        return {"rows": frame.head(QUERY_ROWS).to_dict("records"), "row_count": len(frame), "exec_ms": ms}

    # ------------------------------------------------------------------ options for one decision

    def options(self, side: str, head: str) -> dict:
        return self._red_options(str(head)) if side == "red" else self._blue_options(str(head))

    def _names(self, s) -> dict[str, str]:
        names: dict[str, str] = {}
        sup = s.q("MATCH (x:Supplier) WHERE x.source = 'supply_chain' RETURN x.supplier_id AS k, x.name AS n")
        for k, n in sup.itertuples(index=False):
            names[str(k).split(":")[-1]] = str(n)
        for k, n in s.q("MATCH (x:Site) RETURN x.site_id AS k, x.name AS n").itertuples(index=False):
            names[str(k)] = str(n)
        return names

    def _protected(self, s) -> set[str]:
        if "protected" not in s.property_types:
            return set()
        frame = s.q("MATCH (p:PowerPlant) WHERE p.protected = true RETURN p.gppd_idnr AS g")
        return {str(g) for g in frame["g"]}

    def _red_options(self, head: str) -> dict:
        s = self.lab.graph.session(head)
        scout = scout_targets(self.lab, head)
        protected = self._protected(s)
        plants = [{**p, "protected": p["gppd_idnr"] in protected} for p in scout["site_feeding_plants"]][:6]
        suppliers = scout["top_suppliers_by_critical_demand"][:8]
        if suppliers:
            fallback = {"action": "strike_supplier", "args": {"supplier_id": suppliers[0]["supplier_id"]}}
        else:
            open_plants = [p["gppd_idnr"] for p in plants if not p["protected"]]
            fallback = {"action": "strike_plant", "args": {"gppd_idnr": open_plants[0]}} if open_plants else None
        return {"suppliers_by_critical_demand": suppliers, "site_feeding_plants": plants,
                "sites": [str(x) for x in s.q("MATCH (x:Site) RETURN x.site_id AS k")["k"]],
                "note": scout["note"], "names": self._names(s) | {p["gppd_idnr"]: p["name"] for p in plants},
                "fallback": fallback}

    def _blue_options(self, head: str) -> dict:
        s = self.lab.graph.session(head)
        damage = self.lab.evaluate_branch(head).summary()
        protected = self._protected(s)
        plants = [p for p in scout_targets(self.lab, head)["site_feeding_plants"]
                  if p["gppd_idnr"] not in protected][:5]
        if damage["parts_unavailable"]:
            fallback = {"action": "backup_all_affected_parts", "args": {}}
        elif damage["sites_down"]:
            fallback = {"action": "restore_power", "args": {"facility_id": damage["sites_down"][0]}}
        elif plants:
            fallback = {"action": "prioritise_air_defence", "args": {"gppd_idnr": plants[0]["gppd_idnr"]}}
        else:
            fallback = None
        unavailable = damage["parts_unavailable"]
        coverage = {"backup_all_affected_parts": f"restores all {unavailable} unavailable parts in one move",
                    "add_backup_supplier": "restores 1 part"}
        suggested = fallback["action"] if fallback else None
        return {"suggested": suggested, "coverage": coverage, "damage": damage,
                "unprotected_site_feeding_plants": plants, "protected_plants": sorted(protected),
                "names": self._names(s) | {p["gppd_idnr"]: p["name"] for p in plants}, "fallback": fallback}

    # ------------------------------------------------------------------ map payload

    def effects(self, side: str, parent: str, child: str, actions: list[dict]) -> dict:
        """What the map draws for a move. Red: destroyed nodes, with arcs to the located nodes that lost status
        and to the sites ordering parts that became unavailable. Blue: the providers of the edges this move
        added (backup supplier, power plant, logistics partner), with arcs to what they now serve."""
        diff = self.lab.graph.backend.diff(_ref(parent), _ref(child))
        if side == "blue":
            return self._blue_effects(parent, child, actions, diff)
        hit = [_point(n) for n in diff.removed if _located(n)][:TARGET_CAP] or self._focus(parent, actions)
        affected = [_point(c.node) for c in diff.changed if _located(c.node) and _severity_moved(c, up=True)]
        lost_parts = [c.node.id for c in diff.changed if c.node.label == "Part" and _severity_moved(c, up=True)]
        sites = self._sites_for_parts(child, lost_parts)
        return {"targets": hit, "arcs": _arcs(hit, _dedupe(affected + sites)[:AFFECTED_CAP], "DEPENDS_ON")}

    def _blue_effects(self, parent: str, child: str, actions: list[dict], diff) -> dict:
        added = self._added_edges(child) - self._added_edges(parent)
        s = self.lab.graph.session(str(child))
        providers: list[dict] = []
        arcs: list[dict] = []
        for rel, a, b in sorted(added)[:AFFECTED_CAP]:
            source = self._located_node(s, int(b))
            providers += source
            if not source:
                continue
            served = self._sites_for_parts(child, [a]) if rel == "SUPPLIED_BY" else self._located_node(s, int(a))
            arcs += _arcs(source, served, "RESTORED")
        restored = [_point(c.node) for c in diff.changed if _located(c.node) and _severity_moved(c, up=False)]
        targets = _dedupe(self._focus(child, actions) + providers + restored)[:TARGET_CAP]
        return {"targets": targets, "arcs": _dedupe_arcs(arcs)[:AFFECTED_CAP]}

    def _added_edges(self, branch: str) -> set[tuple[str, str, str]]:
        """(rel, from, to) of every edge a countermeasure added on this branch (edges carry agent_added)."""
        if str(branch) == "main":
            return set()
        s = self.lab.graph.session(str(branch))
        if "agent_added" not in s.property_types:
            return set()
        out: set[tuple[str, str, str]] = set()
        for rel in ("SUPPLIED_BY", "SOURCES_FROM", "POWERED_BY"):
            frame = s.q(f"MATCH (a)-[e:{rel}]->(b) WHERE e.agent_added = true RETURN a, b")
            out |= {(rel, str(a), str(b)) for a, b in frame.itertuples(index=False)}
        return out

    def _sites_for_parts(self, branch: str, part_ids: list[str]) -> list[dict]:
        """Located sites that order these parts (linear path: part <- purchase order -> site)."""
        if not part_ids:
            return []
        s = self.lab.graph.session(str(branch))
        out: dict[str, dict] = {}
        for clause in id_clauses("p", part_ids[:AFFECTED_CAP]):
            frame = s.q(f"MATCH (p:Part)<-[:FOR_PART]-(po:PurchaseOrder)-[:DELIVERED_TO]->(st:Site) WHERE {clause} "
                        "RETURN st, st.name AS name, st.latitude AS lat, st.longitude AS lon")
            for sid, name, lat, lon in frame.dropna(subset=["lat", "lon"]).itertuples(index=False):
                out[str(sid)] = {"id": str(sid), "name": str(name), "kind": "site", "lat": float(lat),
                                 "lon": float(lon), "status": None}
        return list(out.values())

    def _focus(self, branch: str, actions: list[dict]) -> list[dict]:
        """The located node(s) an action names (the plant protected, the site re-powered, ...)."""
        s = self.lab.graph.session(str(branch))
        out = []
        for step in actions:
            args = step.get("args", {}) or {}
            for arg, label, prop in KEY_ARGS:
                key = args.get(arg)
                if not key:
                    continue
                try:
                    if label is None:
                        nid = _resolve_facility(self.lab, s, str(key))
                    elif label == "PowerPlant":
                        nid = self.lab._resolve_plant(s, str(key))
                    else:
                        nid = self.lab._resolve(s, label, prop, str(key))
                except Exception as exc:  # the target may be gone on this ref; the map just skips it
                    log.debug("no focus node for %s=%s: %s", arg, key, exc)
                    continue
                out += self._located_node(s, int(nid))
        return out

    def _located_node(self, s, nid: int) -> list[dict]:
        frame = s.q(f"MATCH (n) WHERE n = {nid} RETURN n.name AS name, n.latitude AS lat, n.longitude AS lon, "
                    "labels(n) AS lbl")
        if frame.empty or frame["lat"].isna().any():
            return []
        row = frame.iloc[0]
        lbl = first_label(row["lbl"])  # a string in 1.37, a list in 3.0
        return [{"id": str(nid), "name": str(row["name"]), "kind": KIND.get(lbl, "other"),
                 "lat": float(row["lat"]), "lon": float(row["lon"]), "status": None}]


def _arcs(sources: list[dict], nodes: list[dict], rel: str) -> list[dict]:
    """One arc per node, from the nearest source (a struck target, or the asset that restored it)."""
    arcs = []
    for n in nodes if sources else []:
        src = min(sources, key=lambda p: (p["lat"] - n["lat"]) ** 2 + (p["lon"] - n["lon"]) ** 2)
        if src["id"] != n["id"]:
            arcs.append({"source": [src["lon"], src["lat"]], "target": [n["lon"], n["lat"]],
                         "source_id": src["id"], "target_id": n["id"], "hop": 1, "rel": rel})
    return arcs


def _dedupe(points: list[dict]) -> list[dict]:
    return list({p["id"]: p for p in points}.values())


def _dedupe_arcs(arcs: list[dict]) -> list[dict]:
    return list({(a["source_id"], a["target_id"]): a for a in arcs}.values())


def scenario_injector(lab: Any):
    """An Injector that runs the scenario agent on the match head (lab: agents.orchestrator.Lab)."""
    def inject(text: str, parent: str, llm: Any) -> InjectResult:
        before = len(lineage_actions(lab.branches, parent))
        trace = run_scenario(lab.branches, llm or lab.llm, text, max_steps=INJECT_STEPS, parent=parent)
        built = [st.observation for st in trace.steps if st.action == "simulate_scenario"
                 and isinstance(st.observation, dict) and st.observation.get("branch")]
        if not built:
            raise RuntimeError(f"the scenario agent built no branch for {text!r}")
        chosen = str((trace.result or {}).get("branch") or "")
        obs = next((b for b in built if str(b["branch"]) == chosen), built[-1])
        rec = lab.branches.record(str(obs["branch"]))
        edits = [a for a in rec.spec["actions"][before:] if a.get("action") != PROPAGATE["action"]]
        result = trace.result or {}
        summary = str(result.get("explanation") or result.get("headline") or
                      f"{obs.get('destroyed_count', 0)} nodes destroyed, supply loss {obs.get('supply_loss_pct')}%")
        return InjectResult(branch_id=str(obs["branch"]), actions=edits, summary=summary[:400])
    return inject
