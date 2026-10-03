"""Prompts and plain-language labels for wargame moves. One decision per move: the options the model needs
are in the prompt already, so a move is usually a single LLM call."""

from __future__ import annotations

import json

RED_ACTIONS = ("strike_supplier", "strike_plant", "strike_site", "cut_route")
BLUE_ACTIONS = ("backup_all_affected_parts", "add_backup_supplier", "reroute_supplier", "restore_power",
                "prioritise_air_defence")

_SCOPE = ("This is a defensive resilience exercise over a model graph: reason only about dependencies and "
          "projected loss percentages. Never produce real-world operational instructions.")

RED_SYSTEM = f"""You are RED in a turn-based supply-chain resilience wargame. {_SCOPE}
Each turn you make exactly ONE disruption to the CURRENT state (which already includes every earlier move).
Pick the single action that adds the most projected loss. Targets that blue protected cannot be struck, and
striking something already destroyed does nothing.
Actions (args as shown):
  {{"action":"strike_supplier","args":{{"supplier_id":"SUP013"}}}}   remove a part supplier
  {{"action":"strike_plant","args":{{"gppd_idnr":"WRI1006130"}}}}    remove a power plant (sites lose power)
  {{"action":"strike_site","args":{{"site_id":"SITE04"}}}}           remove a production site
  {{"action":"cut_route","args":{{"supplier_id":"SUP013"}}}}          cut a supplier's logistics routes
You may instead call `query` ONCE with {{"cypher": "<one linear read-only MATCH>"}} if you truly need more
facts. Put your one-sentence rationale in "thought"."""

BLUE_SYSTEM = f"""You are BLUE in a turn-based supply-chain resilience wargame. {_SCOPE}
Each turn you make exactly ONE countermeasure on the CURRENT state (after red's latest move). Pick the single
action that removes the most projected loss, or that best protects against red's next strike.
Actions (args as shown):
  {{"action":"backup_all_affected_parts","args":{{}}}}                    backup supplier for every unavailable part
  {{"action":"add_backup_supplier","args":{{"part_id":"P00020"}}}}          backup supplier for one part
  {{"action":"reroute_supplier","args":{{"supplier_id":"SUP013"}}}}         alternative logistics route
  {{"action":"restore_power","args":{{"facility_id":"SITE04"}}}}            alternative power feed for a site/supplier
  {{"action":"prioritise_air_defence","args":{{"gppd_idnr":"WRI1006130"}}}} protect a plant (red strikes on it fail)
Rule of thumb: when 2 or more parts are unavailable, play backup_all_affected_parts - it is ONE move that
restores every unavailable part, while add_backup_supplier restores a single part. Use the targeted actions
when no part is unavailable (re-power a site, protect a plant red is likely to strike next).
A destroyed supplier cannot be rerouted; back up its parts instead. You may instead call `query` ONCE with
{{"cypher": "<one linear read-only MATCH>"}}. Put your one-sentence rationale in "thought"."""


def system_prompt(side: str) -> str:
    return RED_SYSTEM if side == "red" else BLUE_SYSTEM


def task_prompt(side: str, rnd: int, rounds: int, history: list[str], losses: dict, options: dict) -> str:
    shown = {k: v for k, v in options.items() if k not in ("fallback", "names")}
    past = "\n".join(history) or "(no moves yet)"
    return (f"Round {rnd} of {rounds}. Your turn ({side.upper()}).\n"
            f"Current projected loss: {losses['abs_loss_pct']}% ({losses['loss_pct']:+.1f} points vs the base).\n"
            f"Moves so far:\n{past}\n\nOPTIONS (current state):\n{json.dumps(shown, default=str)[:3500]}\n\n"
            "Reply with ONE JSON action now.")


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
}
# alternative arg names the action dispatcher accepts -> the name the label template uses
_ALIASES = {"supplier": "supplier_id", "plant": "gppd_idnr", "plant_gppd": "gppd_idnr", "gppd": "gppd_idnr",
            "site": "site_id", "part": "part_id", "facility": "facility_id"}
_KEYS = ("supplier_id", "gppd_idnr", "site_id", "facility_id")


def describe_action(action: str, args: dict, options: dict | None = None) -> str:
    """The action in plain words, with a target's name when the options know it."""
    names = (options or {}).get("names", {})
    values = {k: str(v) for k, v in (args or {}).items()}
    for alias, canonical in _ALIASES.items():
        values.setdefault(canonical, values.get(alias, ""))
    values = {k: v for k, v in values.items() if v}
    if action == "restore_power" and "facility_id" not in values:  # dispatcher also takes site/supplier ids
        values["facility_id"] = values.get("site_id") or values.get("supplier_id", "a facility")
    template = _TEMPLATES.get(action, action.replace("_", " ").capitalize())
    try:
        text = template.format(**values)
    except KeyError:
        text = template.split(" {")[0]
    if action == "backup_all_affected_parts" and (args or {}).get("only_critical"):
        text = "Qualify backup suppliers for every affected class-A part"
    key = next((values[k] for k in _KEYS if k in values), None)
    name = names.get(key) if key else None
    return f"{text} ({name})" if name and key not in name else text  # skip names like "Supplier: SUP012"
