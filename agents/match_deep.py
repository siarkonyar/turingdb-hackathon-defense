"""The deep supply network inside the wargame board: the capability score, deep option names, and the map
payload of deep moves (what to flash or pulse, and arcs to what the move hit or restored)."""

from __future__ import annotations

from agents import deep_impact as D
from agents.match_prompts import BLUE_DEEP, RED_DEEP

DEEP_WEIGHT = 0.75  # the capability score: 75% deep platform production, 25% the original parts layer
TARGET_CAP = 30
ARC_CAP = 80


def combined(legacy: float, deep: float | None) -> float:
    return legacy if deep is None else DEEP_WEIGHT * deep + (1 - DEEP_WEIGHT) * legacy


def names(static: D.Static) -> dict[str, str]:
    out = {i["port_id"]: i["name"] for i in static.ports.values()}
    out |= {i["waypoint_id"]: i["name"] for i in static.chokes.values()}
    out |= {i["facility_id"]: i["name"] for i in static.facilities.values()}
    out |= {iid: name for iid, name, _ in static.items.values()}
    return out


def is_deep(actions: list[dict]) -> bool:
    return any(a.get("action") in RED_DEEP + BLUE_DEEP for a in actions)


# ---------------------------------------------------------------------- map payload


def _facility_point(static: D.Static, f: str) -> dict | None:
    info = static.facilities.get(f)
    if not info or not (info["lat"] or info["lon"]):
        return None
    return {"id": f, "name": info["name"], "kind": "facility", "lat": info["lat"], "lon": info["lon"], "status": None}


def _port_point(static: D.Static, p: str) -> dict:
    i = static.ports[p]
    return {"id": p, "name": i["name"], "kind": "port", "lat": i["lat"], "lon": i["lon"], "status": None}


def _focus(static: D.Static, state: D.State, step: dict) -> list[dict]:
    """The located node(s) a deep move names; an export control is drawn at the controlling country's makers."""
    args = step.get("args", {}) or {}
    port = next((p for p, i in static.ports.items() if i["port_id"] == args.get("port_id")), None)
    if port:
        return [_port_point(static, port)]
    fac = next((f for f, i in static.facilities.items() if i["facility_id"] == args.get("facility_id")), None)
    if fac:
        return [p for p in [_facility_point(static, fac)] if p]
    choke = next((c for c, i in static.chokes.items() if i["waypoint_id"] == args.get("waypoint_id")), None)
    if choke:
        i = static.chokes[choke]
        return [{"id": choke, "name": i["name"], "kind": "other", "lat": i["lat"], "lon": i["lon"], "status": None}]
    item = next((n for n, (iid, _, _) in static.items.items() if iid == args.get("item_id")), None)
    if item:
        cc = args.get("country_code")
        makers = [f for f, _ in state.produced_at.get(item, ())
                  if not cc or static.facilities.get(f, {}).get("cc") == cc]
        return [p for p in (_facility_point(static, f) for f in makers[:TARGET_CAP]) if p]
    return []


def _arcs(sources: list[dict], nodes: list[dict], rel: str) -> list[dict]:
    arcs = []
    for n in nodes if sources else []:
        src = min(sources, key=lambda p: (p["lat"] - n["lat"]) ** 2 + (p["lon"] - n["lon"]) ** 2)
        if src["id"] != n["id"]:
            arcs.append({"source": [src["lon"], src["lat"]], "target": [n["lon"], n["lat"]], "source_id": src["id"],
                         "target_id": n["id"], "hop": 1, "rel": rel})
    return arcs[:ARC_CAP]


def _prime_plants(static: D.Static, state: D.State, platforms: list[str]) -> list[dict]:
    """Final-assembly facilities of these platforms (where the capability change lands)."""
    seen: dict[str, dict] = {}
    for plat in platforms:
        for f, _ in state.produced_at.get(plat, ()):
            point = _facility_point(static, f)
            if point:
                seen[f] = point
    return list(seen.values())


def effects(static: D.Static, side: str, parent: tuple[D.State, D.Result], child: tuple[D.State, D.Result],
            actions: list[dict]) -> dict:
    """Red: flash the disrupted port / chokepoint / facility / controlling makers, arcs to the facilities it
    degraded and the final-assembly plants of platforms that lost output. Blue: pulse the measure's assets
    (incl. the new export port), arcs to what recovered."""
    (p_state, p_res), (c_state, c_res) = parent, child
    worse = side != "blue"
    sign = 1 if worse else -1
    focus = [pt for step in actions for pt in _focus(static, p_state if worse else c_state, step)]
    if not worse:  # a reroute's new port is the thing to pulse
        new_ports = {p for ps in c_state.ships_via.values() for p in ps} - \
                    {p for ps in p_state.ships_via.values() for p in ps}
        focus = [_port_point(static, p) for p in new_ports if p in static.ports] + focus
    moved = [f for f, v in c_res.facility_ok.items() if sign * (p_res.facility_ok.get(f, 1.0) - v) > 1e-9]
    touched = [p for p in (_facility_point(static, f) for f in moved) if p]
    plats = [p for p, v in c_res.platform_avail.items() if sign * (p_res.platform_avail.get(p, 1.0) - v) > 1e-9]
    downstream = _prime_plants(static, c_state, plats)
    targets = list({p["id"]: p for p in focus}.values())[:TARGET_CAP] or touched[:TARGET_CAP]
    ends = list({p["id"]: p for p in touched[:ARC_CAP // 2] + downstream}.values())
    return {"targets": targets, "arcs": _arcs(targets, ends, "DEPENDS_ON" if worse else "RESTORED")}
