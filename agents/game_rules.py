"""Replayable game clock and orders: scarcity must survive branch stacking and recorded replay."""

from __future__ import annotations

import json
import base64

from api.backends.turing_session import string_literal

BUDGET = 14
STOCK_ROUNDS = 2
# Cost in exercise credits, lead time in rounds. These are explicit gameplay assumptions.
MEASURES = {
    "reroute_exports": (2, 0), "replace_facility": (5, 2), "second_source": (3, 2),
    "stockpile": (2, 0), "harden": (3, 1), "backup_all_affected_parts": (6, 2),
    "add_backup_supplier": (2, 1), "reroute_supplier": (2, 0), "restore_power": (3, 1),
    "prioritise_air_defence": (3, 1), "wait": (0, 0),
}


def read_game(s) -> dict:
    if "GameState" not in s.labels:
        return {}
    rows = s.q("MATCH (g:GameState) RETURN g.payload AS payload")
    return json.loads(base64.b64decode(rows["payload"].iloc[0])) if len(rows) else {}


def _write(s, game: dict) -> None:
    # Cypher's string_literal replaces quote/backslash characters. Encode JSON to preserve it exactly.
    payload = string_literal(base64.b64encode(json.dumps(game, sort_keys=True).encode()).decode())
    if "GameState" in s.labels and len(s.q("MATCH (g:GameState) RETURN g")):
        s.q(f"MATCH (g:GameState) SET g.payload = {payload}")
    else:
        s.q(f"CREATE (:GameState {{payload: {payload}}})")
    s.q("COMMIT")
    s.refresh_schema()


def game_init(lab, s, *, rounds: int, seed: int = 7) -> str:
    _write(s, {"version": 1, "round": 0, "rounds": rounds, "budget": BUDGET,
               "pending": [], "stocks": [], "completed": [], "seed": seed, "event_until": -1})
    return "strategic exercise initialized"


def _execute(lab, s, game: dict, step: dict) -> None:
    from agents.actions import apply_action

    if step["action"] == "wait":
        return
    apply_action(lab, s, step["action"], step.get("args", {}))
    if step["action"] == "stockpile":
        game["stocks"].append({"item_id": step["args"]["item_id"], "expires": max(1, game["round"]) + STOCK_ROUNDS})


def game_order(lab, s, *, action: str, args: dict) -> str:
    game = read_game(s)
    if not game:
        raise ValueError("no strategic exercise on this branch")
    if action not in MEASURES:
        raise ValueError("unknown resilience measure")
    cost, delay = MEASURES[action]
    if cost > game["budget"]:
        raise ValueError(f"measure costs {cost}; only {game['budget']} credits remain")
    step = {"action": action, "args": args}
    if any(p["step"] == step for p in game["pending"]):
        raise ValueError("this measure is already pending")
    game["budget"] -= cost
    if delay:
        game["pending"].append({"step": step, "due": game["round"] + delay, "cost": cost})
    else:
        _execute(lab, s, game, step)
    _write(s, game)
    return f"{action}: {cost} credits, ready round {game['round'] + delay}"


def game_tick(lab, s, *, round: int) -> str:
    from agents.deep_actions import _item, _set

    game = read_game(s)
    if round != game["round"] + 1:
        raise ValueError("game clock must advance one round at a time")
    game["round"] = round
    game["completed"] = []
    # Seed chooses which middle round gets a reproducible two-round congestion shock.
    event_round = max(2, game["rounds"] // 2 + game["seed"] % 2)
    if game["rounds"] >= 4 and round == event_round:
        game["event_until"] = round + 2
        game["completed"].append("Event: export capacity reduced 20% for two rounds")
    for stock in list(game["stocks"]):
        if stock["expires"] <= round:
            _set(s, _item(s, stock["item_id"]), "stockpile", "false")
            game["stocks"].remove(stock)
            game["completed"].append(f"Stock exhausted: {stock['item_id']}")
    # Persist the new clock before resolving measures, so capacity previews see today's shock.
    _write(s, game)
    for order in list(game["pending"]):
        if order["due"] <= round:
            try:
                _execute(lab, s, game, order["step"])
                outcome = "Ready"
            except ValueError as exc:
                # A new disruption can invalidate a pending plan. Credits remain spent.
                outcome = f"Failed ({exc})"
            game["pending"].remove(order)
            game["completed"].append(f"{outcome}: {order['step']['action']} {order['step']['args']}")
    _write(s, game)
    return "; ".join(game["completed"]) or f"Round {round}: clock advanced"


GAME_ACTIONS = {"game_init": game_init, "game_order": game_order, "game_tick": game_tick}
