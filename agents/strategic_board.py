"""A match-local board that compares future branches and enforces scarce, delayed recovery."""

from __future__ import annotations

from dataclasses import replace

from agents import deep_impact as D
from agents.deep_actions import blue_candidates, deep_static, red_candidates
from agents.game_rules import BUDGET, MEASURES, read_game
from agents.match_errors import MoveRejected
from agents.match_prompts import describe_action


class StrategicBoard:
    def __init__(self, board, rounds: int, seed: int = 7) -> None:
        self.board, self.rounds, self.seed = board, rounds, seed
        self.priorities: list[str] = []
        self.last_options: dict = {}
        self.banned: str | list[str] | None = None

    def __getattr__(self, name):
        return getattr(self.board, name)

    def initialize(self, base: str) -> str:
        branch = self.board.stack("blue", "Exercise rules", base,
                                  [{"action": "game_init", "args": {"rounds": self.rounds, "seed": self.seed}}])
        deep = self.board.deep(branch)
        static = deep_static(self.board.lab)
        if deep and static:
            eligible = [p for p, value in deep[1].platform_avail.items() if value >= 0.8]
            self.priorities = sorted(eligible, key=lambda p: (-static.platforms[p][2], p))[:3]
        return branch

    def game(self, branch: str) -> dict:
        return read_game(self.board.lab.graph.session(branch))

    def tick(self, head: str, rnd: int) -> tuple[str, list[dict], str]:
        actions = [{"action": "game_tick", "args": {"round": rnd}}]
        branch = self.board.stack("inject", f"Round {rnd} operations", head, actions)
        completed = self.game(branch)["completed"]
        return branch, actions, "; ".join(completed) or f"Round {rnd}: recovery clock advanced"

    def missions(self, head: str) -> list[dict]:
        deep = self.board.deep(head)
        static = deep_static(self.board.lab)
        if not deep or not static:
            return []
        return [{"item_id": static.platforms[p][0], "name": static.platforms[p][1],
                 "capability_pct": round(100 * deep[1].platform_avail[p], 1), "threshold_pct": 80}
                for p in self.priorities]

    def details(self, head: str) -> dict:
        game = self.game(head)
        return {"budget_remaining": game["budget"], "budget_total": BUDGET,
                "pending": game["pending"], "completed": game["completed"],
                "missions": self.missions(head), "round": game["round"],
                "event_active": game["event_until"] > game["round"]}

    def _actions(self, side: str, candidate: dict) -> list[dict]:
        step = {"action": candidate["action"], "args": candidate.get("args", {})}
        return [{"action": "game_order", "args": step}] if side == "blue" else [step]

    def stack(self, side: str, label: str, parent: str, actions: list[dict]) -> str:
        # Replay and clock edits already contain the concrete replayable commands.
        return self.board.stack(side, label, parent, actions)

    def play(self, side: str, label: str, parent: str, step: dict) -> tuple[str, list[dict]]:
        offered = self.last_options.get("deep_candidates", [])
        if not any(c["action"] == step["action"] and c["args"] == step.get("args", {}) for c in offered):
            raise MoveRejected("choose one of the offered legal plans; budget and pending orders are enforced")
        actions = self._actions(side, step)
        return self.board.stack(side, label, parent, actions), actions

    def effects(self, side: str, parent: str, child: str, actions: list[dict]) -> dict:
        return self.board.effects(side, parent, child, actions)

    def _candidates(self, side: str, head: str, banned: str | list[str] | None = None) -> list[dict]:
        deep = self.board.deep(head)
        static = deep_static(self.board.lab)
        game = self.game(head)
        if side == "blue" and game["budget"] < 2:
            return [{"action": "wait", "args": {}, "target": "No affordable measure; await recovery",
                     "cost": 0, "lead_rounds": 0, "ready_round": game["round"], "est_reduction_pct": 0}]
        if deep and static:
            state, result = deep
            candidates = red_candidates(static, state, 2) if side == "red" else blue_candidates(static, state, 2)
            if side == "blue":
                # Proactive options need to exist before damage, including the preparation phase.
                threats = []
                for disruption in red_candidates(static, state, 2):
                    action, args = disruption["action"], disruption["args"]
                    if action == "close_port":
                        nid = next(n for n, i in static.ports.items() if i["port_id"] == args["port_id"])
                        attacked = D.with_changes(state, closed={nid})
                    elif action == "facility_outage":
                        nid = next(n for n, i in static.facilities.items() if i["facility_id"] == args["facility_id"])
                        attacked = D.with_changes(state, closed={nid})
                    elif action == "block_chokepoint":
                        nid = next(n for n, i in static.chokes.items() if i["waypoint_id"] == args["waypoint_id"])
                        attacked = D.with_changes(state, blocked={nid})
                    else:
                        nid = next(n for n, i in static.items.items() if i[0] == args["item_id"])
                        attacked = D.with_changes(state, controls={f"{args['country_code']}|{nid}"})
                    threats.append((attacked, D.evaluate(static, attacked).loss))
                tested = 0
                per_kind: dict[str, int] = {}
                for item in sorted(static.items, key=lambda i: (-static.item_weight.get(i, 0), i)):
                    iid, name, kind = static.items[item]
                    if kind not in ("Component", "Material", "Mineral"):
                        continue
                    if per_kind.get(kind, 0) >= 4:
                        continue
                    per_kind[kind] = per_kind.get(kind, 0) + 1
                    tested += 1
                    if item not in state.stockpiled:
                        prevention = max((100 * (loss - D.evaluate(static, D.with_changes(attacked, stockpiled={item})).loss)
                                          for attacked, loss in threats), default=0)
                        if prevention >= 0.1:
                            candidates.append({"action": "stockpile", "args": {"item_id": iid}, "target": name,
                                               "est_reduction_pct": 0, "prevents_pct": round(prevention, 1)})
                    fac = D.second_source(static, state, item, result.facility_ok)
                    if fac:
                        prevention = max((100 * (loss - D.evaluate(static, replace(attacked,
                            produced_at={**attacked.produced_at, item: attacked.produced_at.get(item, ()) + ((fac, 50),)})).loss)
                            for attacked, loss in threats), default=0)
                        if prevention >= 0.1:
                            candidates.append({"action": "second_source", "args": {"item_id": iid}, "target": name,
                                               "est_reduction_pct": 0, "prevents_pct": round(prevention, 1)})
                    if tested >= 12:
                        break
        else:
            opts = self.board.options(side, head)
            candidates = [c for c in [opts.get("fallback"), *opts.get("alternates", [])] if c]
        seen = set()
        legal = []
        bans = {banned} if isinstance(banned, str) else set(banned or [])
        for c in candidates:
            action, args = c["action"], c.get("args", {})
            key = (action, tuple(sorted(args.items())))
            if key in seen or action in bans:
                continue
            seen.add(key)
            if side == "blue":
                cost, delay = MEASURES[action]
                if cost > game["budget"] or any(p["step"] == {"action": action, "args": args} for p in game["pending"]):
                    continue
                if game["round"] + delay > self.rounds:
                    continue
                c = {**c, "cost": cost, "lead_rounds": delay, "ready_round": game["round"] + delay,
                     "within_horizon": game["round"] + delay <= self.rounds}
            legal.append(c)
        if side == "blue":
            legal.append({"action": "wait", "args": {}, "target": "Save credits / await recovery",
                          "cost": 0, "lead_rounds": 0, "ready_round": game["round"], "est_reduction_pct": 0})
        return sorted(legal, key=lambda c: -max(c.get("est_gain_pct", 0), c.get("est_reduction_pct", 0),
                                               0.5 * c.get("prevents_pct", 0)))

    def _discard(self, branches: list[str]) -> None:
        for branch in reversed(branches):
            self.board._deep_cache.pop(branch, None)
            self.board.lab.discard(branch)

    def _preview(self, side: str, head: str, candidate: dict) -> dict:
        branches: list[str] = []
        try:
            trial = self.board.stack(side, "Planning preview", head, self._actions(side, candidate))
            branches.append(trial)
            immediate = self.board.loss(trial)
            current = self.game(trial)["round"]
            horizon = min(self.rounds, max(1, current + 2))
            opponent = "blue" if side == "red" else "red"
            # Blue forecasts the next round's state, after recovery/expiry/events, and RED's cooldown
            # still applies there. Never preview an opponent move that is illegal in the real match.
            if side == "blue" and current < self.rounds:
                trial = self.board.stack("inject", "Planning clock", trial,
                                         [{"action": "game_tick", "args": {"round": current + 1}}])
                branches.append(trial)
                current += 1
            responses = self._candidates(opponent, trial, self.banned if opponent == "red" else None)
            # One strongest plausible response per plan; this is bounded lookahead, not exhaustive search.
            response = next((c for c in responses if c["action"] != "wait"), None)
            if side == "blue" and self.game(head)["round"] >= self.rounds:
                response = None
            exposure = immediate
            samples = 1
            if response:
                trial = self.board.stack(opponent, "Opponent preview", trial, self._actions(opponent, response))
                branches.append(trial)
                exposure += self.board.loss(trial)
                samples += 1
            while current < horizon:
                trial = self.board.stack("inject", "Planning recovery", trial,
                                         [{"action": "game_tick", "args": {"round": current + 1}}])
                branches.append(trial)
                current += 1
                exposure += self.board.loss(trial)
                samples += 1
            future = self.board.loss(trial)
            return {"branches_evaluated": len(branches), "response": describe_action(response["action"], response["args"]) if response else "none",
                    "immediate_loss_pct": round(100 * immediate, 1), "future_loss_pct": round(100 * future, 1),
                    "average_loss_pct": round(100 * exposure / samples, 1), "horizon_round": horizon,
                    "missions": self.missions(trial)}
        except MoveRejected as exc:
            return {"error": str(exc)}
        finally:
            self._discard(branches)

    def options(self, side: str, head: str) -> dict:
        candidates = self._candidates(side, head, self.banned if side == "red" else None)
        # Include a production disruption, rather than letting maritime moves hide it behind their
        # larger immediate scores. Three distinct kinds still keep branch work bounded.
        kinds = set()
        ordered = list(candidates)
        if side == "red":
            production = next((c for c in candidates if c["action"] in ("facility_outage", "export_controls")), None)
            if production and ordered:
                ordered = [ordered[0], production] + [c for c in ordered[1:] if c is not production]
        for c in ordered:
            if c["action"] not in kinds and c["action"] != "wait" and len(kinds) < 3:
                kinds.add(c["action"])
                c["planning"] = self._preview(side, head, c)
        previewed = [c for c in candidates if c.get("planning") and "error" not in c["planning"]]
        if previewed:
            previewed.sort(key=lambda c: (sum(m["capability_pct"] < 80 for m in c["planning"]["missions"]),
                                          c["planning"]["average_loss_pct"]), reverse=side == "red")
            best = previewed[0]
            candidates = [best] + [c for c in candidates if c is not best]
        self.last_options = {"deep_candidates": candidates, "exercise": self.details(head),
                             "planning_note": "Up to three alternative graph branches, each against one plausible response; previews are discarded.",
                             "names": self.board.options(side, head).get("names", {}),
                             "fallback": {"action": candidates[0]["action"], "args": candidates[0]["args"]} if candidates else None,
                             "alternates": [{"action": c["action"], "args": c["args"]} for c in candidates[1:]]}
        return self.last_options
