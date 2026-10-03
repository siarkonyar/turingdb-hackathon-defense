"""Wargame moves on the deep supply network: disruption events for red, resilience measures for blue.

Red's moves are abstract disruption events of the kinds the dataset already records (maritime closures,
export controls, facility outages): no means, only an effect on the graph. Blue's moves are the standard
supply-chain resilience levers. Every move is a branch edit, so it is replayable from the branch spec, and
the candidate lists preview each option's effect with the in-memory model (agents/deep_impact.py).
"""

from __future__ import annotations

import threading
from dataclasses import replace

from api.backends.turing_session import Session, string_literal

from agents import deep_impact as D
from agents.branches import BranchLab

RED_DEEP = ("close_port", "block_chokepoint", "export_controls", "facility_outage")
BLUE_DEEP = ("reroute_exports", "replace_facility", "second_source", "stockpile", "harden")
CANDIDATES_PER_KIND = 4
SECOND_SOURCE_SHARE = 50.0
MIN_USEFUL_PCT = 0.1  # measures previewed below this do not reach the model
_static_lock = threading.Lock()


def deep_static(lab: BranchLab) -> D.Static | None:
    """The main-branch structure, loaded once per lab (None when the graph has no deep layer)."""
    with _static_lock:
        if not hasattr(lab, "_deep_static"):
            main = lab.graph.session("main")
            lab._deep_static = D.load_static(main) if {"Platform", "Facility"} <= main.labels else None
        return lab._deep_static


# ---------------------------------------------------------------------- lookups


def _node(s: Session, label: str, key_prop: str, key: str) -> int:
    frame = s.q(f"MATCH (n:{label}) WHERE n.{key_prop} = {string_literal(str(key))} RETURN n")
    if frame.empty:
        raise ValueError(f"no {label} with {key_prop} {key!r}")
    return int(frame["n"].iloc[0])


def _item(s: Session, item_id: str) -> int:
    for label in reversed(D.ITEM_LABELS):  # Mineral ... Platform
        if label in s.labels:
            frame = s.q(f"MATCH (n:{label}) WHERE n.item_id = {string_literal(str(item_id))} RETURN n")
            if not frame.empty:
                return int(frame["n"].iloc[0])
    raise ValueError(f"no bill-of-materials item with item_id {item_id!r}")


def _set(s: Session, nid: int, prop: str, value: str) -> None:
    s.q(f"MATCH (n) WHERE n = {nid} SET n.{prop} = {value}")
    s.q("COMMIT")


def _is_protected(s: Session, nid: int) -> bool:
    s.refresh_schema()  # `protected` may have been set earlier in this branch's lineage
    if "protected" not in s.property_types:
        return False
    return not s.q(f"MATCH (n) WHERE n = {nid} AND n.protected = true RETURN n").empty


# ---------------------------------------------------------------------- red: disruption events


def close_port(lab: BranchLab, s: Session, *, port_id: str) -> str:
    nid = _node(s, "Port", "port_id", port_id)
    if _is_protected(s, nid):
        raise ValueError(f"port {port_id} is hardened on this branch; the closure fails")
    _set(s, nid, D.CLOSED_PROP, "true")
    return f"closed port {port_id}"


def block_chokepoint(lab: BranchLab, s: Session, *, waypoint_id: str) -> str:
    _set(s, _node(s, "Chokepoint", "waypoint_id", waypoint_id), D.CLOSED_PROP, "true")
    return f"blocked chokepoint {waypoint_id}"


def export_controls(lab: BranchLab, s: Session, *, country_code: str, item_id: str) -> str:
    static = deep_static(lab)
    cc = str(country_code).upper()
    if static is not None and cc in static.allied:
        raise ValueError(f"{cc} is a NATO/EU country; export controls come from outside the alliance")
    nid = _item(s, item_id)
    current = ""
    s.refresh_schema()
    if D.CONTROLS_PROP in s.property_types:
        frame = s.q(f"MATCH (n) WHERE n = {nid} RETURN n.{D.CONTROLS_PROP} AS c")
        current = str(frame["c"].iloc[0] or "") if len(frame) and frame["c"].notna().any() else ""
    codes = sorted({c for c in current.split(",") if c} | {cc})
    _set(s, nid, D.CONTROLS_PROP, string_literal(",".join(codes)))
    return f"{cc} export controls on {item_id}"


def facility_outage(lab: BranchLab, s: Session, *, facility_id: str) -> str:
    nid = _node(s, "Facility", "facility_id", facility_id)
    if _is_protected(s, nid):
        raise ValueError(f"facility {facility_id} is hardened on this branch; the outage fails")
    _set(s, nid, D.CLOSED_PROP, "true")
    return f"facility {facility_id} out of action"


# ---------------------------------------------------------------------- blue: resilience measures


def reroute_exports(lab: BranchLab, s: Session, *, port_id: str) -> str:
    static = deep_static(lab)
    port = str(_node(s, "Port", "port_id", port_id))
    alts, users = D.reroute_plan(static, D.load_state(s), port)
    if not alts:
        raise ValueError(f"no better export port than {port_id} for its {len(users)} facilities")
    for fac, alt in D.reroute_assignment(alts, users).items():  # one COMMIT: busy ports have 100s of exporters
        lab.add_edge(s, int(fac), int(alt), "SHIPS_VIA", {"alternative_route": "true"}, commit=False)
    s.q("COMMIT")
    spread = ", ".join(static.ports[a]["port_id"] for a in alts)
    return f"rerouted {len(users)} facilities from {port_id} across {spread}"


def replace_facility(lab: BranchLab, s: Session, *, facility_id: str) -> str:
    """Qualify a replacement maker for every item an out-of-action facility produced."""
    static = deep_static(lab)
    fac = str(_node(s, "Facility", "facility_id", facility_id))
    state = D.load_state(s)
    plan = D.replacement_plan(static, state, fac, D.evaluate(static, state).facility_ok)
    if not plan:
        raise ValueError(f"no qualified replacement found for the items of {facility_id}")
    for item, alt in plan.items():
        lab.add_edge(s, int(item), int(alt), "PRODUCED_AT",
                     {"share_pct": SECOND_SOURCE_SHARE, "second_source": "true"}, commit=False)
    s.q("COMMIT")
    return f"qualified replacements for {len(plan)} items of {facility_id}"


def second_source(lab: BranchLab, s: Session, *, item_id: str) -> str:
    static = deep_static(lab)
    item = str(_item(s, item_id))
    state = D.load_state(s)
    fac = D.second_source(static, state, item, D.evaluate(static, state).facility_ok)
    if fac is None:
        raise ValueError(f"no working facility of the right type can be qualified for {item_id}")
    lab.add_edge(s, int(item), int(fac), "PRODUCED_AT",
                 {"share_pct": SECOND_SOURCE_SHARE, "second_source": "true"})
    return f"qualified {static.facilities[fac]['facility_id']} as second source for {item_id}"


def stockpile(lab: BranchLab, s: Session, *, item_id: str) -> str:
    _set(s, _item(s, item_id), "stockpile", "true")
    return f"strategic stockpile of {item_id}"


def harden(lab: BranchLab, s: Session, *, facility_id: str | None = None, port_id: str | None = None) -> str:
    if port_id:
        nid, what = _node(s, "Port", "port_id", port_id), f"port {port_id}"
    elif facility_id:
        nid, what = _node(s, "Facility", "facility_id", facility_id), f"facility {facility_id}"
    else:
        raise ValueError("harden needs facility_id or port_id")
    _set(s, nid, "protected", "true")
    return f"hardened {what} (closures / outages on it fail)"


DEEP_ACTIONS = {
    "close_port": close_port, "block_chokepoint": block_chokepoint, "export_controls": export_controls,
    "facility_outage": facility_outage, "reroute_exports": reroute_exports, "second_source": second_source,
    "stockpile": stockpile, "harden": harden, "replace_facility": replace_facility,
}


# ---------------------------------------------------------------------- previewed candidates


def _delta(static: D.Static, base: float, state: D.State) -> float:
    return round(100 * (D.evaluate(static, state).loss - base), 1)


def _best(cands: list[dict], key: str, n: int) -> list[dict]:
    return sorted(cands, key=lambda c: c[key], reverse=True)[:n]


def _export_users(state: D.State, ok: dict[str, float]) -> dict[str, int]:
    users: dict[str, int] = {}
    for fac, ports in state.ships_via.items():
        if ok.get(fac, 0) > 0:
            for p in ports:
                users[p] = users.get(p, 0) + 1
    return users


def red_candidates(static: D.Static, state: D.State, n: int = CANDIDATES_PER_KIND) -> list[dict]:
    """The strongest disruptions of each kind, each with its previewed loss gain (percentage points)."""
    base = D.evaluate(static, state)

    def option(action: str, args: dict, target: str, trial: D.State, **extra) -> dict:
        return {"action": action, "args": args, "target": target,
                "est_gain_pct": _delta(static, base.loss, trial), **extra}

    chokes = [option("block_chokepoint", {"waypoint_id": i["waypoint_id"]}, i["name"],
                     D.with_changes(state, blocked={c}))
              for c, i in static.chokes.items() if c not in state.blocked]
    users = _export_users(state, base.facility_ok)
    busy = sorted((p for p in users if p not in state.closed and p not in state.protected), key=lambda p: -users[p])
    ports = [option("close_port", {"port_id": static.ports[p]["port_id"]}, static.ports[p]["name"],
                    D.with_changes(state, closed={p}), exporters=users[p]) for p in busy[:3 * n]]
    sole: dict[str, float] = {}
    for item, makers in state.produced_at.items():
        live = [f for f, _ in makers if base.facility_ok.get(f, 0) > 0]
        if len(live) == 1 and live[0] not in state.protected:
            sole[live[0]] = sole.get(live[0], 0.0) + static.item_weight.get(item, 0.0)
    facs = [option("facility_outage", {"facility_id": static.facilities[f]["facility_id"]},
                   static.facilities[f]["name"], D.with_changes(state, closed={f}), single_point_of_failure=True)
            for f in sorted(sole, key=lambda f: -sole[f])[:3 * n]]
    pairs = sorted(((share * static.item_weight.get(item, 0.0), cc, item)
                    for item, shares in static.country_share.items() for cc, share in shares.items()
                    if cc not in static.allied and f"{cc}|{item}" not in state.controls), reverse=True)[:3 * n]
    ctrl = [option("export_controls", {"country_code": cc, "item_id": static.items[item][0]},
                   f"{cc} on {static.items[item][1]} ({static.country_share[item][cc]:.0f}% of world output)",
                   D.with_changes(state, controls={f"{cc}|{item}"}))
            for _, cc, item in pairs]
    out = [c for group in (chokes, ports, facs, ctrl) for c in _best(group, "est_gain_pct", n)]
    return sorted(out, key=lambda c: -c["est_gain_pct"])


def blue_candidates(static: D.Static, state: D.State, n: int = CANDIDATES_PER_KIND) -> list[dict]:
    """Resilience measures aimed at the current damage, each with its previewed loss reduction; plus
    hardening of red's likeliest next targets (valued at what red's move would have cost)."""
    base = D.evaluate(static, state)
    reroutes, sources, stocks, hardens = [], [], [], []
    for p in static.ports:
        if D.port_factor(static, state, p) >= 1.0:
            continue
        alts, users = D.reroute_plan(static, state, p)
        if not alts:
            continue
        moved = {**state.ships_via, **{f: state.ships_via[f] + (a,) for f, a in D.reroute_assignment(alts, users).items()}}
        reroutes.append({"action": "reroute_exports", "args": {"port_id": static.ports[p]["port_id"]},
                         "target": f"{static.ports[p]['name']} -> " + " / ".join(static.ports[a]["name"] for a in alts)
                                   + f" ({len(users)} facilities)",
                         "est_reduction_pct": -_delta(static, base.loss, replace(state, ships_via=moved))})
    replaces = []
    for f, v in base.facility_ok.items():
        if v > 0 or f not in state.facilities:
            continue
        plan = D.replacement_plan(static, state, f, base.facility_ok)
        if not plan:
            continue
        made = dict(state.produced_at)
        for item, alt in plan.items():
            made[item] = made.get(item, ()) + ((alt, SECOND_SOURCE_SHARE),)
        replaces.append({"action": "replace_facility", "args": {"facility_id": static.facilities[f]["facility_id"]},
                         "target": f"{static.facilities[f]['name']} ({len(plan)} items)",
                         "est_reduction_pct": -_delta(static, base.loss, replace(state, produced_at=made))})
    short = sorted((i for i, a in base.item_avail.items() if a < 0.999 and i in static.items),
                   key=lambda i: -(1 - base.item_avail[i]) * static.item_weight.get(i, 0.0))[:3 * n]
    for item in short:
        iid, name, label = static.items[item]
        fac = D.second_source(static, state, item, base.facility_ok)
        if fac is not None:
            made = {**state.produced_at, item: state.produced_at.get(item, ()) + ((fac, SECOND_SOURCE_SHARE),)}
            sources.append({"action": "second_source", "args": {"item_id": iid},
                            "target": f"{name} at {static.facilities[fac]['name']}",
                            "est_reduction_pct": -_delta(static, base.loss, replace(state, produced_at=made))})
        if item not in state.stockpiled and label in ("Component", "Material", "Mineral"):
            stocks.append({"action": "stockpile", "args": {"item_id": iid}, "target": name,
                           "est_reduction_pct": -_delta(static, base.loss, D.with_changes(state, stockpiled={item}))})
    for c in red_candidates(static, state, 2):
        if c["action"] in ("close_port", "facility_outage"):
            key = "port_id" if c["action"] == "close_port" else "facility_id"
            hardens.append({"action": "harden", "args": {key: c["args"][key]}, "target": c["target"],
                            "est_reduction_pct": 0.0, "prevents_pct": c["est_gain_pct"]})
    useful = [[c for c in group if c["est_reduction_pct"] >= MIN_USEFUL_PCT] for group in (reroutes, replaces, sources, stocks)]
    out = [c for group in useful for c in _best(group, "est_reduction_pct", n)]
    out += _best(hardens, "prevents_pct", n)
    return sorted(out, key=lambda c: -max(c["est_reduction_pct"], 0.5 * c.get("prevents_pct", 0.0)))
