"""Strategy actions: the attack, countermeasure and scenario edits an agent applies inside a branch.

Each action is small, graph-grounded and replayable (its args go into the branch spec). Attacks remove
capacity; defences add redundancy (backup supplier, alternative route, power feed, air-defence priority);
the scenario wipe destroys everything inside a bounding box. All of them change only the branch.
"""

from __future__ import annotations

import logging
import math
from typing import Callable

from api.backends.turing_session import Session, id_clauses, string_literal

from agents.branches import BranchLab, BranchRecord

log = logging.getLogger("agents.actions")
# located labels a disaster wipe destroys, including the supply_chain_deep Facility / Port nodes
WIPE_LABELS = ["PowerPlant", "Site", "Supplier", "Drone", "Crime", "Person", "Location", "Facility", "Port"]


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _xy(s: Session, node_id: int) -> tuple[float, float] | None:
    frame = s.q(f"MATCH (n) WHERE n = {node_id} RETURN n.latitude AS lat, n.longitude AS lon")
    if frame.empty or frame["lat"].isna().all():
        return None
    return float(frame["lat"].iloc[0]), float(frame["lon"].iloc[0])


def _working_suppliers(s: Session) -> set[str]:
    powered = {str(x) for x in s.q("MATCH (x:Supplier)-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
    routed = {str(x) for x in s.q("MATCH (x:Supplier)-[:SOURCES_FROM]->(l:Supplier) RETURN x")["x"]}
    return powered & routed


def _surviving_plants(s: Session, near: tuple[float, float] | None, limit: int = 1) -> list[int]:
    frame = s.q("MATCH (p:PowerPlant) RETURN p, p.latitude AS lat, p.longitude AS lon, p.capacity_mw AS mw").dropna(
        subset=["lat", "lon"])
    rows = [(int(p), float(la), float(lo), float(mw or 0)) for p, la, lo, mw in frame.itertuples(index=False)]
    if near is not None:
        rows.sort(key=lambda r: _km(near[0], near[1], r[1], r[2]))
    else:
        rows.sort(key=lambda r: -r[3])
    return [r[0] for r in rows[:limit]]


# ---------------------------------------------------------------------- attacks (threat agent)

def attack_delete(lab: BranchLab, s: Session, *, label: str, key_prop: str, key: str) -> str:
    node = lab._resolve(s, label, key_prop, key)
    if lab.is_protected(s, node):
        return f"{label} {key} is air-defence protected on this branch; strike refused"
    name = _name(s, node)
    lab.delete_node(s, node)
    return f"deleted {label} {name}"


def attack_cut_route(lab: BranchLab, s: Session, *, supplier_id: str) -> str:
    node = lab._resolve(s, "Supplier", "supplier_id", supplier_id)
    s.q(f"MATCH (x)-[e:SOURCES_FROM]->(l:Supplier) WHERE x = {node} DELETE e")
    s.q("COMMIT")
    return f"cut all logistics routes of supplier {supplier_id}"


# ---------------------------------------------------------------------- defences (defence agent)

def defend_backup_supplier(lab: BranchLab, s: Session, *, part_id: str, supplier_id: str | None = None) -> str:
    part = lab._resolve(s, "Part", "part_id", part_id)
    working = _working_suppliers(s)
    already = {str(x) for x in s.q(f"MATCH (p)-[:SUPPLIED_BY]->(x:Supplier) WHERE p = {part} RETURN x")["x"]}
    if supplier_id is not None:
        sup = lab._resolve(s, "Supplier", "supplier_id", supplier_id)
    else:
        candidates = [int(x) for x in working - already]
        if not candidates:
            return f"no spare working supplier available for part {part_id}"
        sup = candidates[0]
    lab.add_edge(s, part, sup, "SUPPLIED_BY", {"backup": "true"})
    return f"added backup supplier {_sid(s, sup)} for part {part_id}"


def defend_backup_all(lab: BranchLab, s: Session, *, only_critical: bool = False) -> str:
    """Qualify a backup working supplier for every part left unavailable on this branch (optionally only
    class-A). One countermeasure that closes all remaining supply gaps the attack opened."""
    working = _working_suppliers(s)
    supplied = s.q("MATCH (p:Part)-[:SUPPLIED_BY]->(x:Supplier) RETURN p, x")
    have: dict[str, set[str]] = {}
    for p, x in supplied.itertuples(index=False):
        have.setdefault(str(p), set()).add(str(x))
    spare = [int(x) for x in working]
    if not spare:
        return "no working supplier available to serve as a backup"
    classes = s.q("MATCH (p:Part) RETURN p, p.criticality_class AS cc")
    added = 0
    for p, cc in classes.itertuples(index=False):
        pid = str(p)
        if only_critical and str(cc) != "A":
            continue
        if have.get(pid, set()) & working:
            continue  # already has a working supplier
        pick = next((x for x in spare if x not in have.get(pid, set())), spare[0])
        lab.add_edge(s, int(pid), pick, "SUPPLIED_BY", {"backup": "true"})
        added += 1
    return f"qualified backup suppliers for {added} {'critical ' if only_critical else ''}parts"


def defend_reroute(lab: BranchLab, s: Session, *, supplier_id: str, logistics_id: str | None = None) -> str:
    node = lab._resolve(s, "Supplier", "supplier_id", supplier_id)
    cc = _prop(s, node, "country_code")
    if logistics_id is not None:
        alt = lab._resolve(s, "Supplier", "supplier_id", logistics_id)
    else:
        frame = s.q("MATCH (l:Supplier) WHERE l.source = 'logistics_risk' RETURN l, l.country_code AS cc, "
                    "l.supplier_id AS sid")
        same = [int(l) for l, c, _ in frame.itertuples(index=False) if str(c) == str(cc)]
        alt = (same or [int(frame["l"].iloc[0])])[0] if len(frame) else None
        if alt is None:
            return f"no alternative logistics route available for {supplier_id}"
    lab.add_edge(s, node, alt, "SOURCES_FROM", {"alternative_route": "true"})
    return f"rerouted supplier {supplier_id} via alternative logistics partner {_sid(s, alt)}"


def defend_restore_power(lab: BranchLab, s: Session, *, facility_id: str, plant_gppd: str | None = None) -> str:
    node = _resolve_facility(lab, s, facility_id)
    xy = _xy(s, node)
    if plant_gppd is not None:
        plant = lab._resolve_plant(s, plant_gppd)
    else:
        plants = _surviving_plants(s, xy, limit=1)
        if not plants:
            return "no surviving plant to draw power from"
        plant = plants[0]
    lab.add_edge(s, node, plant, "POWERED_BY", {"alternative_feed": "true"})
    return f"restored power to {facility_id} from plant {_name(s, plant)}"


def defend_air_defence(lab: BranchLab, s: Session, *, plant_gppd: str) -> str:
    """Prioritise air defence on a plant: flag it protected and restore feeds from it to facilities that
    lost power. Protection makes a later threat strike on this plant fail."""
    plant = lab._resolve_plant(s, plant_gppd)
    lab.protect_node(s, plant, "air_defence_priority")
    xy = _xy(s, plant)
    restored = 0
    for label in ("Site", "Supplier"):
        frame = s.q(f"MATCH (f:{label}) RETURN f, f.latitude AS lat, f.longitude AS lon").dropna(subset=["lat", "lon"])
        powered = {str(x) for x in s.q(f"MATCH (x:{label})-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
        for f, la, lo in frame.itertuples(index=False):
            if str(f) in powered:
                continue
            if xy is None or _km(xy[0], xy[1], float(la), float(lo)) <= 400:
                lab.add_edge(s, int(f), plant, "POWERED_BY", {"air_defence_restored": "true"})
                restored += 1
    s.q("COMMIT")
    return f"air-defence priority on {_name(s, plant)}; restored power to {restored} facilities"


# ---------------------------------------------------------------------- scenario wipe (scenario agent)



def scenario_wipe_bbox(lab: BranchLab, s: Session, *, west: float, south: float, east: float, north: float,
                       labels: list[str] | None = None) -> str:
    """Destroy every located node inside a bounding box (a catastrophic-event footprint), including the
    supply_chain_deep facilities and ports there."""
    targets = [t for t in (labels or WIPE_LABELS) if t in s.labels]
    inside = (f"n.latitude >= {float(south)} AND n.latitude <= {float(north)} "
              f"AND n.longitude >= {float(west)} AND n.longitude <= {float(east)}")
    removed = 0
    for label in targets:
        count = int(s.q(f"MATCH (n:{label}) WHERE {inside} RETURN count(n) AS c")["c"].iloc[0])
        if count:
            # one filtered delete per label: ~0.3 s for a city, vs ~23 s deleting 9k nodes one query each.
            # DETACH: TuringDB 3.0 refuses to delete a node that still has edges.
            s.q(f"MATCH (n:{label}) WHERE {inside} DETACH DELETE n")
            removed += count
    if removed:
        s.q("COMMIT")
    return f"destroyed {removed} nodes inside bbox ({west},{south},{east},{north})"


def scenario_wipe_node(lab: BranchLab, s: Session, *, label: str, key_prop: str, key: str) -> str:
    return attack_delete(lab, s, label=label, key_prop=key_prop, key=key)


def scenario_propagate(lab: BranchLab, s: Session) -> str:
    """Mark downstream effects on the branch so the map overlay and KPIs show them: a facility with no
    surviving POWERED_BY feed becomes 'no_power'; a part supplier still powered but with no logistics route
    becomes 'at_risk'; a part with no working supplier left becomes 'at_risk' (the impact model's rule, see
    agents/impact.py); a deep Facility that had a POWERED_BY feed on main and has none left becomes 'no_power',
    one that lost a supplier (a main-branch SUPPLIES source no longer exists) becomes 'at_risk'. The sets are
    disjoint, so a node never ends up with two statuses."""
    # Only Sites and PART suppliers (source=supply_chain) are modelled as drawing power; logistics
    # suppliers never have a POWERED_BY feed, so they must not be flagged for lacking one.
    site_ids = {str(x) for x in s.q("MATCH (x:Site) RETURN x")["x"]}
    powered_sites = {str(x) for x in s.q("MATCH (x:Site)-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
    part_sup = {str(x) for x in s.q("MATCH (x:Supplier) WHERE x.source = 'supply_chain' RETURN x")["x"]}
    powered_sup = {str(x) for x in s.q("MATCH (x:Supplier)-[:POWERED_BY]->(p:PowerPlant) RETURN x")["x"]}
    routed = {str(x) for x in s.q("MATCH (x:Supplier)-[:SOURCES_FROM]->(l:Supplier) RETURN x")["x"]}
    working = part_sup & powered_sup & routed
    supplied = s.q("MATCH (p:Part)-[:SUPPLIED_BY]->(x:Supplier) RETURN p, x")
    available = {str(p_) for p_, x in supplied.itertuples(index=False) if str(x) in working}
    parts = {str(x) for x in s.q("MATCH (p:Part) RETURN p")["p"]}
    no_power = (site_ids - powered_sites) | (part_sup - powered_sup)
    at_risk = {x for x in part_sup if x in powered_sup and x not in routed} | (parts - available)
    if "Facility" in s.labels:  # supply_chain_deep layer
        main = lab.graph.session("main")
        fac = {str(x) for x in s.q("MATCH (f:Facility) RETURN f")["f"]}
        fed_main = {str(x) for x in main.q("MATCH (f:Facility)-[:POWERED_BY]->(p:PowerPlant) RETURN DISTINCT f")["f"]}
        fed_now = {str(x) for x in s.q("MATCH (f:Facility)-[:POWERED_BY]->(p:PowerPlant) RETURN DISTINCT f")["f"]}
        no_power |= (fac & fed_main) - fed_now
        links = main.q("MATCH (a:Facility)-[:SUPPLIES]->(b:Facility) RETURN a, b")
        at_risk |= {str(b) for a, b in links.itertuples(index=False) if str(a) not in fac and str(b) in fac}
        at_risk |= _deep_disrupted(lab, s)
    at_risk = sorted(at_risk - no_power)
    no_power = sorted(no_power)
    for status, ids in (("no_power", no_power), ("at_risk", at_risk)):
        for clause in id_clauses("n", ids):  # chunked OR-of-ids writes, not one query per node
            s.q(f"MATCH (n) WHERE {clause} SET n.ops_status = '{status}'")
    s.q("COMMIT")
    unavailable = len(parts - available)
    return (f"propagated downstream impact: {len(no_power)} without power, {len(at_risk) - unavailable} "
            f"suppliers at risk, {unavailable} parts unavailable")


def _deep_disrupted(lab: BranchLab, s: Session) -> set[str]:
    """Deep-layer nodes a wargame disruption degraded (facilities below full output, closed ports)."""
    from agents import deep_impact as D
    from agents.deep_actions import deep_static

    static = deep_static(lab)
    if static is None:
        return set()
    state = D.load_state(s)
    ok = D.evaluate(static, state).facility_ok
    ports = {p for p in static.ports if p in state.ports and D.port_factor(static, state, p) < 1.0}
    return {f for f, v in ok.items() if v < 1.0 and f in state.facilities} | ports


# ---------------------------------------------------------------------- dispatch + replay

def _pick(args: dict, *names: str, required: bool = True) -> str | None:
    for n in names:
        if args.get(n) not in (None, ""):
            return str(args[n])
    if required:
        raise ValueError(f"missing one of {names}")
    return None


ActionFn = Callable[..., str]
ACTIONS: dict[str, ActionFn] = {
    "strike_plant": lambda lab, s, **k: attack_delete(
        lab, s, label="PowerPlant", key_prop="gppd_idnr", key=_pick(k, "gppd_idnr", "plant_gppd", "gppd", "plant")),
    "strike_supplier": lambda lab, s, **k: attack_delete(
        lab, s, label="Supplier", key_prop="supplier_id", key=_pick(k, "supplier_id", "supplier")),
    "strike_site": lambda lab, s, **k: attack_delete(
        lab, s, label="Site", key_prop="site_id", key=_pick(k, "site_id", "site")),
    "cut_route": lambda lab, s, **k: attack_cut_route(lab, s, supplier_id=_pick(k, "supplier_id", "supplier")),
    "add_backup_supplier": lambda lab, s, **k: defend_backup_supplier(
        lab, s, part_id=_pick(k, "part_id", "part"), supplier_id=_pick(k, "supplier_id", "supplier", required=False)),
    "backup_all_affected_parts": lambda lab, s, **k: defend_backup_all(
        lab, s, only_critical=bool(k.get("only_critical", False))),
    "reroute_supplier": lambda lab, s, **k: defend_reroute(
        lab, s, supplier_id=_pick(k, "supplier_id", "supplier"),
        logistics_id=_pick(k, "logistics_id", "logistics_supplier", required=False)),
    "restore_power": lambda lab, s, **k: defend_restore_power(
        lab, s, facility_id=_pick(k, "facility_id", "site_id", "supplier_id", "facility"),
        plant_gppd=_pick(k, "plant_gppd", "gppd_idnr", "gppd", required=False)),
    "prioritise_air_defence": lambda lab, s, **k: defend_air_defence(
        lab, s, plant_gppd=_pick(k, "plant_gppd", "gppd_idnr", "gppd", "plant")),
    "wipe_bbox": scenario_wipe_bbox,
    "wipe_node": scenario_wipe_node,
    "propagate": lambda lab, s, **k: scenario_propagate(lab, s),
    # deep supply network (agents/deep_actions.py): red disruption events, blue resilience measures
    "close_port": lambda lab, s, **k: _deep("close_port")(lab, s, port_id=_pick(k, "port_id", "port")),
    "block_chokepoint": lambda lab, s, **k: _deep("block_chokepoint")(
        lab, s, waypoint_id=_pick(k, "waypoint_id", "chokepoint_id", "chokepoint")),
    "export_controls": lambda lab, s, **k: _deep("export_controls")(
        lab, s, country_code=_pick(k, "country_code", "country"), item_id=_pick(k, "item_id", "item", "material")),
    "facility_outage": lambda lab, s, **k: _deep("facility_outage")(lab, s, facility_id=_pick(k, "facility_id")),
    "reroute_exports": lambda lab, s, **k: _deep("reroute_exports")(lab, s, port_id=_pick(k, "port_id", "port")),
    "second_source": lambda lab, s, **k: _deep("second_source")(lab, s, item_id=_pick(k, "item_id", "item")),
    "replace_facility": lambda lab, s, **k: _deep("replace_facility")(lab, s, facility_id=_pick(k, "facility_id")),
    "stockpile": lambda lab, s, **k: _deep("stockpile")(lab, s, item_id=_pick(k, "item_id", "item")),
    "harden": lambda lab, s, **k: _deep("harden")(
        lab, s, facility_id=_pick(k, "facility_id", required=False), port_id=_pick(k, "port_id", required=False)),
}


def _deep(name: str) -> ActionFn:
    from agents.deep_actions import DEEP_ACTIONS  # late import: deep_actions imports this package's lab

    return DEEP_ACTIONS[name]


def apply_action(lab: BranchLab, s: Session, name: str, args: dict) -> str:
    if name.startswith("game_"):
        from agents.game_rules import GAME_ACTIONS

        fn = GAME_ACTIONS.get(name)
        if fn is None:
            raise ValueError(f"unknown game action {name!r}")
        return fn(lab, s, **(args or {}))
    fn = ACTIONS.get(name)
    if fn is None:
        raise ValueError(f"unknown action {name!r}; known: {sorted(ACTIONS)}")
    return fn(lab, s, **(args or {}))


def replay_branch(lab: BranchLab, rec: BranchRecord) -> None:
    """Rebuild one branch from its spec after a server restart (same actions, fresh change)."""
    actions = rec.spec.get("actions", [])
    s, new = lab.open_branch(rec.role, rec.label, rec.spec, parent=rec.parent)
    for step in actions:
        apply_action(lab, s, step["action"], step.get("args", {}))
    lab.evaluate_branch(new.change_id)
    log.info("replayed branch %s as %s", rec.change_id, new.change_id)


# ---------------------------------------------------------------------- small helpers

def _name(s: Session, node_id: int) -> str:
    frame = s.q(f"MATCH (n) WHERE n = {node_id} RETURN n.name AS name")
    return str(frame["name"].iloc[0]) if len(frame) and frame["name"].notna().any() else str(node_id)


def _sid(s: Session, node_id: int) -> str:
    return _prop(s, node_id, "supplier_id") or str(node_id)


def _prop(s: Session, node_id: int, prop: str) -> str | None:
    if prop not in s.property_types:
        return None
    frame = s.q(f"MATCH (n) WHERE n = {node_id} RETURN n.{prop} AS v")
    return str(frame["v"].iloc[0]) if len(frame) and frame["v"].notna().any() else None


def _resolve_facility(lab: BranchLab, s: Session, key: str) -> int:
    if key.isdigit():
        return int(key)
    for label, prop in (("Site", "site_id"), ("Supplier", "supplier_id")):
        frame = s.q(f"MATCH (n:{label}) WHERE n.{prop} = {string_literal(key)} RETURN n")
        if not frame.empty:
            return int(frame["n"].iloc[0])
    raise ValueError(f"no Site or Supplier with id {key!r}")
