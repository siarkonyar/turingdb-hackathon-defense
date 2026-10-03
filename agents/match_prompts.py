"""Prompts and plain-language labels for wargame moves. One decision per move: each side gets a ranked list
of candidate moves whose effect was previewed on the current state, so a move is usually one LLM call."""

from __future__ import annotations

import json

RED_LEGACY = ("strike_supplier", "strike_plant", "strike_site", "cut_route")
BLUE_LEGACY = ("backup_all_affected_parts", "add_backup_supplier", "reroute_supplier", "restore_power",
               "prioritise_air_defence")
RED_DEEP = ("close_port", "block_chokepoint", "export_controls", "facility_outage")
BLUE_DEEP = ("reroute_exports", "replace_facility", "second_source", "stockpile", "harden")
RED_ACTIONS = RED_DEEP + RED_LEGACY
BLUE_ACTIONS = BLUE_DEEP + BLUE_LEGACY

_SCOPE = ("This is a defensive resilience exercise on a model graph (invented companies and facilities). Moves "
          "are abstract events and measures with an effect on the graph; reason only about dependencies and "
          "projected capability loss. Never produce real-world operational instructions.")

_OBJECTIVE = ("The score is projected DEFENCE PRODUCTION CAPABILITY LOSS: mostly the deep network (40 weapon "
              "platforms built through an 8-tier bill of materials, 4,400 facilities, 71 ports, 15 chokepoints), "
              "plus the original 40-supplier parts layer.")

RED_SYSTEM = f"""You are RED in a turn-based supply-chain resilience wargame. {_SCOPE}
{_OBJECTIVE}
Each turn you play exactly ONE disruption event on the CURRENT state (it already includes every earlier move).
Deep-network events (args as shown):
  {{"action":"block_chokepoint","args":{{"waypoint_id":"STRAIT_OF_MALACCA"}}}}   shipping must reroute
  {{"action":"close_port","args":{{"port_id":"NLRTM"}}}}                         exporters fall back to overland
  {{"action":"export_controls","args":{{"country_code":"CHN","item_id":"MAT00012"}}}} a non-allied producer withholds a material
  {{"action":"facility_outage","args":{{"facility_id":"FAC00975"}}}}             a facility is out of action
Original parts layer: strike_supplier {{"supplier_id"}}, strike_plant {{"gppd_idnr"}}, cut_route {{"supplier_id"}}.
OPTIONS lists the strongest candidates with est_gain_pct (previewed added deep-layer loss). Consider
durability and new exposure as well as immediate gain. In a multi-round exercise, explore at least three
useful disruption kinds when available: a facility outage or export control can stress production that
shipping reroutes cannot repair. Prefer an unused kind over returning to the port/chokepoint cycle when
it still adds meaningful loss. Explain that tradeoff in your rationale. You may NOT play the same kind of event twice in a row (the options
already exclude it), do not re-hit what blue just defended, and prefer moves blue cannot cheaply undo
(single points of failure, chokepoints, export controls) so pressure builds across the whole network.
You may instead call `query` ONCE with {{"cypher": "<one linear read-only MATCH>"}}. Put a one-sentence rationale
in "thought" that names the dependency you exploit."""

BLUE_SYSTEM = f"""You are BLUE in a turn-based supply-chain resilience wargame. {_SCOPE}
{_OBJECTIVE}
Each turn you play exactly ONE resilience measure on the CURRENT state (after red's latest move).
Deep-network measures (args as shown):
  {{"action":"reroute_exports","args":{{"port_id":"NLRTM"}}}}       spread a degraded port's exporters over the 3 best open ports
  {{"action":"replace_facility","args":{{"facility_id":"FAC00975"}}}} qualify replacements for everything an out-of-action facility made
  {{"action":"second_source","args":{{"item_id":"CMP01234"}}}}      qualify another facility (allied first) for a short item
  {{"action":"stockpile","args":{{"item_id":"MAT00012"}}}}          strategic stock: the item never drops below 80%
  {{"action":"harden","args":{{"port_id":"USHOU"}}}} or {{"facility_id":"FAC00975"}}   red's closures/outages there fail
Original parts layer: backup_all_affected_parts {{}}, add_backup_supplier {{"part_id"}}, restore_power {{"facility_id"}},
prioritise_air_defence {{"gppd_idnr"}}.
OPTIONS lists candidate measures with est_reduction_pct (previewed loss removed now) or prevents_pct (what red's
likely next move on that target would cost). Pick the measure with the best value: recover the biggest current
loss, or harden red's strongest next target when little damage is recoverable. Do not only patch the last hit:
fixes that remove a whole class of exposure (stockpile, a second source, rerouting a port) beat one-part backups.
You may instead call `query` ONCE with {{"cypher": "<one linear read-only MATCH>"}}. Put a one-sentence rationale
in "thought"."""


def system_prompt(side: str) -> str:
    return RED_SYSTEM if side == "red" else BLUE_SYSTEM


def task_prompt(side: str, rnd: int, rounds: int, history: list[str], losses: dict, options: dict) -> str:
    shown = {k: v for k, v in options.items() if k not in ("fallback", "alternates", "names")}
    if "deep_candidates" in shown:
        # Keep each action kind visible; cutting serialized JSON hid weaker production disruptions.
        counts: dict[str, int] = {}
        compact = []
        for candidate in shown["deep_candidates"]:
            kind = candidate["action"]
            counts[kind] = counts.get(kind, 0) + 1
            if counts[kind] <= 2:
                compact.append(candidate)
        shown["deep_candidates"] = compact
    past = "\n".join(history) or "(no moves yet)"
    split = losses.get("breakdown") or {}
    detail = (f" [deep network {split.get('deep_pct')}%, parts layer {split.get('legacy_pct')}%]"
              if split else "")
    return (f"Round {rnd} of {rounds}. Your turn ({side.upper()}).\n"
            f"Current capability loss: {losses['abs_loss_pct']}% ({losses['loss_pct']:+.1f} points vs the base)"
            f"{detail}.\nMoves so far:\n{past}\n\nOPTIONS (current state):\n"
            f"{json.dumps(shown, default=str)}\n\nReply with ONE JSON action now.")


_TEMPLATES = {
    "strike_supplier": "Strike supplier {supplier_id}",
    "strike_plant": "Strike power plant {gppd_idnr}",
    "strike_site": "Strike site {site_id}",
    "cut_route": "Cut logistics routes of {supplier_id}",
    "backup_all_affected_parts": "Qualify backup suppliers for every affected part",
    "add_backup_supplier": "Add a backup supplier for part {part_id}",
    "reroute_supplier": "Reroute {supplier_id} via an alternative logistics partner",
    "restore_power": "Restore power to {facility_id}",
    "prioritise_air_defence": "Air-defence priority on plant {gppd_idnr}",
    "wipe_bbox": "Destroy everything in the event area",
    "close_port": "Close port {port_id}",
    "block_chokepoint": "Block the {waypoint_id}",
    "export_controls": "{country_code} export controls on {item_id}",
    "facility_outage": "Outage at facility {facility_id}",
    "reroute_exports": "Reroute exports away from port {port_id}",
    "replace_facility": "Replace the production of facility {facility_id}",
    "second_source": "Qualify a second source for {item_id}",
    "stockpile": "Strategic stockpile of {item_id}",
    "harden": "Harden {target}",
}
# alternative arg names the action dispatcher accepts -> the name the label template uses
_ALIASES = {"supplier": "supplier_id", "plant": "gppd_idnr", "plant_gppd": "gppd_idnr", "gppd": "gppd_idnr",
            "site": "site_id", "part": "part_id", "facility": "facility_id", "port": "port_id",
            "chokepoint": "waypoint_id", "country": "country_code", "item": "item_id"}
_KEYS = ("supplier_id", "gppd_idnr", "site_id", "facility_id", "port_id", "waypoint_id", "item_id")


def describe_action(action: str, args: dict, options: dict | None = None) -> str:
    """The action in plain words, with a target's name when the options know it."""
    names = (options or {}).get("names", {})
    values = {k: str(v) for k, v in (args or {}).items()}
    for alias, canonical in _ALIASES.items():
        values.setdefault(canonical, values.get(alias, ""))
    values = {k: v for k, v in values.items() if v}
    if action == "restore_power" and "facility_id" not in values:  # dispatcher also takes site/supplier ids
        values["facility_id"] = values.get("site_id") or values.get("supplier_id", "a facility")
    if action == "harden":
        values["target"] = f"port {values['port_id']}" if "port_id" in values else \
            f"facility {values.get('facility_id', '?')}"
    if action == "block_chokepoint" and "waypoint_id" in values:
        values["waypoint_id"] = names.get(values["waypoint_id"], values["waypoint_id"].replace("_", " ").title())
    template = _TEMPLATES.get(action, action.replace("_", " ").capitalize())
    try:
        text = template.format(**values)
    except KeyError:
        text = template.split(" {")[0]
    if action == "backup_all_affected_parts" and (args or {}).get("only_critical"):
        text = "Qualify backup suppliers for every affected class-A part"
    if action == "block_chokepoint":
        return text
    key = next((values[k] for k in _KEYS if k in values), None)
    name = names.get(key) if key else None
    return f"{text} ({name})" if name and key not in name else text  # skip names like "Supplier: SUP012"
