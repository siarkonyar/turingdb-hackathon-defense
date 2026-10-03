"""Turn-based red-vs-blue wargame over stacked TuringDB branches.

A match starts on a base branch (main or a scenario). Each round red makes ONE disruption, built as a
branch stacked on the current head, then blue makes ONE countermeasure stacked on red's branch; the head
moves forward each time. Loss is measured against the base, so after a scenario the numbers mean
"additional damage on top of the scenario". Between rounds an operator can inject an event (the scenario
agent runs on the head and its branch becomes the head). Every match is saved to matches/<id>.json and can
be replayed with the original timing and no LLM calls (branches are rebuilt from the recorded edits).

    uv run python -m agents.match --base 25 --rounds 3 --inject 2:"the Liverpool port is closed"
    uv run python -m agents.match --replay demo
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from agents.config import ROOT
from agents.engine import PROTOCOL
from agents.llm import LLMError, LLMUnavailable, parse_action
from agents.match_errors import MoveRejected
from agents.match_prompts import BLUE_ACTIONS, RED_ACTIONS, describe_action, system_prompt, task_prompt

log = logging.getLogger("agents.match")

MATCHES_DIR = ROOT / "matches"
MOVE_STEPS = 3  # one decision; a format retry or one read query at most
MOVE_MAX_TOKENS = 350
_FILE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

Emit = Callable[[str, dict], None]


class MatchStopped(Exception):
    pass


class Board(Protocol):
    """Everything a match does to TuringDB. LabBoard (agents/match_board.py) is the live one."""

    def loss(self, branch: str) -> float: ...
    def stack(self, side: str, label: str, parent: str, actions: list[dict]) -> str: ...
    def options(self, side: str, head: str) -> dict: ...
    def effects(self, side: str, parent: str, child: str, actions: list[dict]) -> dict: ...
    def query(self, branch: str, cypher: str) -> dict: ...
    def lineage(self, branch: str) -> list[dict]: ...
    def rebuild(self, label: str, actions: list[dict]) -> str: ...


class ChatModel(Protocol):
    model: str

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


@dataclass(frozen=True)
class InjectResult:
    branch_id: str
    actions: list[dict]  # the edits the event added on top of the head
    summary: str


Injector = Callable[[str, str, Any], InjectResult]  # (event text, parent branch, chat model) -> new branch


@dataclass(frozen=True)
class Move:
    round: int
    side: str  # red | blue | inject
    action: str
    args: dict
    actions: list[dict]  # the edits this move added on top of its parent (replayable)
    branch_id: str
    parent_id: str
    label: str  # the action in plain words
    rationale: str
    loss_pct: float  # additional projected loss vs the base, percentage points
    abs_loss_pct: float
    llm_ms: float
    db_ms: float
    latency_ms: float
    targets: list[dict] = field(default_factory=list)  # {id, name, kind, lat, lon} for the map
    arcs: list[dict] = field(default_factory=list)  # {source, target, source_id, target_id, hop, rel}
    fallback: bool = False  # the model gave no valid move; a deterministic default was played
    breakdown: dict = field(default_factory=dict)  # {deep_pct, legacy_pct}: absolute loss per layer
    selection: dict = field(default_factory=dict)
    llm_calls: int = 0
    llm_requests: int = 0
    strategy: dict = field(default_factory=dict)  # budget, recovery deadlines, missions, planning alternatives

    def as_dict(self) -> dict:
        return asdict(self)


class _TimedModel:
    """Wraps a chat model and accumulates the wall time of its calls."""

    def __init__(self, llm: ChatModel) -> None:
        self.llm, self.ms, self.calls = llm, 0.0, 0
        self.initial_requests = getattr(getattr(llm, "usage", None), "requests", 0)

    @property
    def requests(self) -> int:
        return getattr(getattr(self.llm, "usage", None), "requests", self.calls) - self.initial_requests

    @property
    def model(self) -> str:
        return self.llm.model

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        started = time.perf_counter()
        self.calls += 1
        try:
            return self.llm.chat(messages, **kwargs)
        finally:
            self.ms += (time.perf_counter() - started) * 1000


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pct(x: float) -> float:
    return round(100 * x, 1)


def match_path(name: str, directory: Path = MATCHES_DIR) -> Path:
    """matches/<name>.json for a bare, safe name (no paths): the replay/list boundary."""
    stem = name[:-5] if name.endswith(".json") else name
    if not _FILE.match(stem):
        raise ValueError(f"invalid match file {name!r}: use letters, digits, '-' or '_'")
    return directory / f"{stem}.json"


class Match:
    def __init__(self, board: Board, base_branch: str = "main", rounds: int = 3, *, llm: ChatModel | None,
                 injector: Injector | None = None, emit: Emit | None = None, match_id: str | None = None,
                 directory: Path = MATCHES_DIR, save_as: str | None = None,
                 strategic: bool = False, seed: int = 7) -> None:
        if rounds < 1:
            raise ValueError("rounds must be >= 1")
        self.id = match_id or uuid.uuid4().hex[:8]
        self.board, self.base, self.rounds = board, str(base_branch), rounds
        self.llm, self.injector = llm, injector
        self.head = self.base
        self.moves: list[Move] = []
        self.events: list[dict] = []
        self.state = "pending"
        self.path = match_path(save_as or self.id, directory)
        self._emit_cb = emit or (lambda _t, _d: None)
        self._injects: list[str] = []
        self._lock = threading.Lock()
        self._emit_lock = threading.RLock()
        self._running = threading.Event()
        self._running.set()
        self._stop = threading.Event()
        self._started = time.perf_counter()
        self._ended: float | None = None
        self.base_loss = 0.0
        self.base_actions: list[dict] = []
        self.strategic, self.seed = strategic, seed
        self.cumulative_loss = 0.0
        self.round_scores: list[dict] = []

    # ------------------------------------------------------------------ operator controls (any thread)

    def inject(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("inject text is empty")
        with self._lock:
            if self.state in ("done", "stopped", "error"):
                raise ValueError(f"match is {self.state}")
            self._injects.append(text)
            return len(self._injects)

    def pause(self) -> None:
        self._running.clear()
        self._set_state("paused")

    def resume(self) -> None:
        self._running.set()
        self._set_state("running")

    def stop(self) -> None:
        self._stop.set()
        self._running.set()

    # ------------------------------------------------------------------ the loop

    def run(self) -> dict:
        try:
            self._start()
            if self.strategic:
                self._checkpoint()
                self._emit("move_started", {"round": 0, "side": "blue", "head": self.head})
                self._record(self._play("blue", 0))
            for rnd in range(1, self.rounds + 1):
                if self.strategic:
                    self._checkpoint()
                    started = time.perf_counter()
                    branch, actions, label = self.board.tick(self.head, rnd)
                    clock = self._finalise("inject", rnd - 1, "game_tick", {"round": rnd}, actions,
                                           branch, label, label, 0, started, False)
                    self._record(clock)
                    self._emit("inject", {"text": label, "branch": branch, "move": clock.as_dict()})
                self._drain_injects(rnd)
                for side in ("red", "blue"):
                    self._checkpoint()
                    self._emit("move_started", {"round": rnd, "side": side, "head": self.head})
                    self._record(self._play(side, rnd))
                missions = self.board.missions(self.head) if self.strategic else []
                self.round_scores.append({"round": rnd, "cumulative_loss": round(self.cumulative_loss, 1),
                                          "missions": missions,
                                          "objective_met": bool(missions) and all(m["capability_pct"] >= 80 for m in missions)})
                self._emit("round_done", {"round": rnd, "head": self.head, **self._losses(self.head)})
            self._drain_injects(self.rounds + 1)  # an event queued during the last round still lands
            return self._finish("done")
        except MatchStopped:
            return self._finish("stopped")
        except Exception as exc:
            log.exception("match %s failed", self.id)
            self._emit("error", {"message": f"{type(exc).__name__}: {exc}", "replay_available": True})
            return self._finish("error")

    def _start(self) -> None:
        self._set_state("running", emit=False)
        self.base_loss = self.board.loss(self.base)
        self.base_actions = self.board.lineage(self.base)
        if self.strategic:
            from agents.strategic_board import StrategicBoard

            self.board = StrategicBoard(self.board, self.rounds, self.seed)
            initialized = self.board.initialize(self.base)
            # Record initialization as a concrete move so replay reconstructs the same game clock.
            started = time.perf_counter()
            init = self._finalise("inject", 0, "game_init", {},
                                  [{"action": "game_init", "args": {"rounds": self.rounds, "seed": self.seed}}],
                                  initialized, "Exercise rules: 14 credits; protect priority programmes above 80%",
                                  "Finite capacity, delayed recovery, two-round stocks and partial hardening.", 0, started, False)
            self.moves.append(init)
            self.head = initialized
        self._emit("match_started", {"match_id": self.id, "base_branch": self.base, "rounds": self.rounds,
                                     "base_loss_pct": _pct(self.base_loss),
                                     "model": getattr(self.llm, "model", None), "strategic": self.strategic})
        if self.strategic:
            self._emit("inject", {"text": init.label, "branch": init.branch_id, "move": init.as_dict()})

    def _checkpoint(self) -> None:
        if self._stop.is_set():
            raise MatchStopped
        if not self._running.is_set():
            self._running.wait()
            if self._stop.is_set():
                raise MatchStopped

    def _drain_injects(self, before_round: int) -> None:
        while True:
            with self._lock:
                if not self._injects:
                    return
                text = self._injects.pop(0)
            self._checkpoint()
            self._apply_inject(text, before_round - 1)

    def _apply_inject(self, text: str, after_round: int) -> None:
        if self.injector is None:
            raise RuntimeError("this match has no injector")
        self._emit("move_started", {"round": after_round, "side": "inject", "head": self.head, "text": text})
        timed = _TimedModel(self.llm) if self.llm is not None else None
        started = time.perf_counter()
        result = self.injector(text, self.head, timed)
        first = result.actions[0] if result.actions else {"action": "event", "args": {}}
        move = self._finalise("inject", after_round, first["action"], first.get("args", {}), result.actions,
                              result.branch_id, f"Event: {text}", result.summary, timed.ms if timed else 0.0,
                              started, fallback=False)
        move = replace(move, llm_calls=timed.calls if timed else 0,
                       llm_requests=timed.requests if timed else 0)
        self._record(move)
        self._emit("inject", {"text": text, "branch": move.branch_id, "move": move.as_dict()})

    def _play(self, side: str, rnd: int) -> Move:
        from agents.blue_selection import BlueSelector

        selector = BlueSelector()
        timed = _TimedModel(self.llm) if self.llm is not None else None
        started = time.perf_counter()
        audit = ({"selector": "existing_blue", "fallback": False, "candidates": [], "jev_calls": 0}
                 if side == "blue" else {})
        opts = None
        if side == "blue" and selector.settings.enabled and timed:
            if getattr(self, "strategic", False):
                self.board.banned = [m.action for m in reversed(self.moves) if m.side == "red"][:2]
            opts = self.board.options(side, self.head)
            offered = opts.get("deep_candidates") or [c for c in
                [opts.get("fallback"), *opts.get("alternates", [])] if c]
            if not (len(offered) == 1 and offered[0]["action"] == "wait"):
                state = {"round": rnd, "rounds": self.rounds, "history": self._history(),
                         "damage": opts.get("damage") or opts.get("parts_layer", {}).get("damage"),
                         "exercise": opts.get("exercise")}

                def validate(step):
                    branch = None
                    try:
                        label = describe_action(step["action"], step["args"], opts)
                        branch = (self.board.play(side, label, self.head, step)[0] if getattr(self, "strategic", False) else
                                  self.board.stack(side, label, self.head, [step]))
                        source = next((c for c in offered if c["action"] == step["action"]
                                       and c.get("args", {}) == step["args"]), {})
                        before_imp = self.board.lab.evaluate_branch(self.head)
                        after_imp = self.board.lab.evaluate_branch(branch)
                        return {"loss_pct": _pct(self.board.loss(branch)),
                                "critical_parts_restored": sorted(set(before_imp.critical_parts_unavailable) -
                                                                   set(after_imp.critical_parts_unavailable)),
                                **({"priority_programmes": self.board.missions(branch)} if getattr(self, "strategic", False) else {}),
                                **{k: source[k] for k in ("cost", "ready_round", "name") if k in source}}
                    except MoveRejected:
                        return None
                    finally:
                        if branch:
                            self.board.lab.discard(branch)
                            self.board._deep_cache.pop(branch, None)

                step, audit = selector.select(timed, state, validate, offered)
                if step:
                    label = describe_action(step["action"], step["args"], opts)
                    try:
                        branch, edits = (self.board.play(side, label, self.head, step) if getattr(self, "strategic", False) else
                                         (self.board.stack(side, label, self.head, [step]), [step]))
                    except MoveRejected:
                        audit.update(selector="existing_blue", fallback=True, reason="execution_rejected")
                    else:
                        outcome = {"loss_before_pct": _pct(self.board.loss(self.head)),
                                   "loss_after_pct": _pct(self.board.loss(branch))}
                        audit["impact"] = outcome
                        why = selector.explain(timed, audit, outcome)
                        move = self._finalise(side, rnd, step["action"], step["args"], edits, branch,
                                              label, why, timed.ms, started, False)
                        return replace(move, selection=audit, llm_calls=timed.calls, llm_requests=timed.requests,
                                       db_ms=round(max(0, move.db_ms - audit["request_ms"]), 1))
        move = self._play_existing(side, rnd, opts=opts, timed=timed, started=started)
        if audit:
            audit["impact"] = {"loss_before_pct": _pct(self.board.loss(move.parent_id)),
                               "loss_after_pct": move.abs_loss_pct}
            audit["executed"] = {"action": move.action, "args": move.args}
        return replace(move, selection=audit, llm_calls=timed.calls if timed else 0,
                       llm_requests=timed.requests if timed else 0,
                       db_ms=round(max(0, move.db_ms - audit.get("request_ms", 0)), 1))

    def _play_existing(self, side: str, rnd: int, *, opts=None, timed=None, started=None) -> Move:
        started = started or time.perf_counter()
        banned = self._last_action(side) if side == "red" else None  # red must vary its disruption kind
        cooldown = [m.action for m in reversed(self.moves) if m.side == "red"][:2]
        bans = cooldown if self.strategic and side == "red" else ([banned] if banned else [])
        if self.strategic:
            self.board.banned = cooldown
        allowed = tuple(a for a in (RED_ACTIONS if side == "red" else BLUE_ACTIONS + ("wait",)) if a not in bans)
        opts = _without(opts if opts is not None else self.board.options(side, self.head),
                        bans if self.strategic else banned)
        candidates = opts.get("deep_candidates", [])
        if self.strategic and side == "blue" and len(candidates) == 1 and candidates[0]["action"] == "wait":
            step = {"action": "wait", "args": {}}
            label = describe_action("wait", {})
            branch, edits = self.board.play(side, label, self.head, step)
            return self._finalise(side, rnd, "wait", {}, edits, branch, label,
                                  "Automatic wait: no affordable measure can complete within the match horizon.",
                                  0, started, fallback=False)
        messages = [{"role": "system", "content": f"{system_prompt(side)}\n\n{PROTOCOL}"},
                    {"role": "user", "content": task_prompt(side, rnd, self.rounds, self._history(),
                                                            self._losses(self.head), opts)}]
        for _ in range(MOVE_STEPS if timed else 0):
            try:
                reply = timed.chat(messages, agent=side, temperature=0.3, max_tokens=MOVE_MAX_TOKENS)
            except LLMUnavailable:
                raise
            except LLMError as exc:
                log.warning("%s model response failed; using a legal fallback: %s", side, exc)
                return self._fallback(side, rnd, opts, timed.ms, started)
            messages.append({"role": "assistant", "content": reply})
            try:
                act = parse_action(reply)
            except ValueError as exc:
                messages.append({"role": "user", "content": f"FORMAT ERROR: {exc}"})
                continue
            name, args, why = act["action"], act.get("args", {}), str(act.get("thought", "")).strip()
            if name == "query":
                obs: Any = self.board.query(self.head, str(args.get("cypher", "")))
            elif name not in allowed:
                obs = {"error": f"{name!r} is not a {side} action; choose one of {list(allowed)}"}
            else:
                step = {"action": name, "args": args}
                label = describe_action(name, args, opts)
                try:
                    if self.strategic:
                        branch, edits = self.board.play(side, label, self.head, step)
                    else:
                        branch, edits = self.board.stack(side, label, self.head, [step]), [step]
                except MoveRejected as exc:
                    obs = {"error": str(exc)}
                else:
                    return self._finalise(side, rnd, name, args, edits, branch, label, why, timed.ms, started,
                                          fallback=False)
            messages.append({"role": "user", "content": "OBSERVATION:\n" + json.dumps(obs, default=str)[:2500]})
        return self._fallback(side, rnd, opts, timed.ms if timed else 0.0, started)

    def _last_action(self, side: str) -> str | None:
        return next((m.action for m in reversed(self.moves) if m.side == side), None)

    def _fallback(self, side: str, rnd: int, opts: dict, llm_ms: float, started: float) -> Move:
        """The model gave no valid move: play the top-ranked default, or the next one if the board refuses it."""
        steps = [s for s in [opts.get("fallback"), *opts.get("alternates", [])] if s]
        if not steps:
            raise RuntimeError(f"{side} produced no valid move and the board offered no default")
        errors = []
        for step in steps:
            label = describe_action(step["action"], step.get("args", {}), opts)
            try:
                if self.strategic:
                    branch, edits = self.board.play(side, label, self.head, step)
                else:
                    branch, edits = self.board.stack(side, label, self.head, [step]), [step]
            except MoveRejected as exc:
                errors.append(str(exc))
                continue
            return self._finalise(side, rnd, step["action"], step.get("args", {}), edits, branch, label,
                                  "Model gave no valid move; played the top-ranked default.", llm_ms, started,
                                  fallback=True)
        raise RuntimeError(f"{side} had no playable move: {'; '.join(errors)[:400]}")

    def _finalise(self, side: str, rnd: int, action: str, args: dict, actions: list[dict], branch: str,
                  label: str, rationale: str, llm_ms: float, started: float, fallback: bool) -> Move:
        parent = self.head
        effects = self.board.effects(side, parent, branch, actions)
        losses = self._losses(branch)
        total_ms = (time.perf_counter() - started) * 1000
        strategy = {}
        if self.strategic:
            strategy = self.board.details(branch)
            candidates = self.board.last_options.get("deep_candidates", [])
            chosen = next((c for c in candidates if c["action"] == action and c["args"] == args), {})
            strategy.update({"cost": chosen.get("cost", 0), "ready_round": chosen.get("ready_round", rnd),
                             "cumulative_loss": round(self.cumulative_loss +
                                                      (max(0, losses["loss_pct"]) * 0.5 if side in ("red", "blue") and rnd > 0 else 0), 1),
                             "planning": chosen.get("planning"),
                             "alternatives": [{"label": describe_action(c["action"], c["args"]),
                                               "cost": c.get("cost", 0), "ready_round": c.get("ready_round", rnd),
                                               "planning": c.get("planning")}
                                              for c in candidates if c is not chosen and c.get("planning")][:2]})
        return Move(round=rnd, side=side, action=action, args=args, actions=actions, branch_id=branch,
                    parent_id=parent, label=label, rationale=rationale or label, loss_pct=losses["loss_pct"],
                    abs_loss_pct=losses["abs_loss_pct"], llm_ms=round(llm_ms, 1),
                    db_ms=round(max(0.0, total_ms - llm_ms), 1), latency_ms=round(total_ms, 1),
                    targets=effects.get("targets", []), arcs=effects.get("arcs", []), fallback=fallback,
                    breakdown=losses.get("breakdown", {}), strategy=strategy)

    def _record(self, move: Move) -> None:
        self.moves.append(move)
        self.head = move.branch_id
        if move.side in ("red", "blue") and move.round > 0:
            self.cumulative_loss += max(0, move.loss_pct) * 0.5
        if move.side != "inject":
            self._emit("move", move.as_dict())
        log.info("[%s] r%d %s %s -> #%s (%+.1f%%, llm %.0f ms, db %.0f ms)", self.id, move.round, move.side,
                 move.label, move.branch_id, move.loss_pct, move.llm_ms, move.db_ms)

    def _finish(self, status: str) -> dict:
        self._ended = time.perf_counter()
        self._set_state(status, emit=False)
        summary = self.summary()
        self._emit("match_done", {"status": status, "summary": summary})
        return summary

    # ------------------------------------------------------------------ views

    def _losses(self, branch: str) -> dict:
        loss = self.board.loss(branch)
        split = getattr(self.board, "breakdown", None)
        return {"loss_pct": _pct(loss - self.base_loss), "abs_loss_pct": _pct(loss),
                **({"breakdown": split(branch)} if split else {})}

    def _history(self) -> list[str]:
        return [f"R{m.round} {m.side}: {m.label} -> {m.loss_pct:+.1f}% vs base" for m in self.moves[-8:]]

    def summary(self) -> dict:
        played = [m for m in self.moves if m.side != "inject"]
        duration = 0.5 * sum(m.round > 0 for m in played)
        return {"match_id": self.id, "status": self.state, "base_branch": self.base, "head": self.head,
                "rounds_played": max((m.round for m in played), default=0),
                "base_loss_pct": _pct(self.base_loss),
                "final_loss_pct": self.moves[-1].loss_pct if self.moves else 0.0,
                "red_moves": sum(m.side == "red" for m in self.moves),
                "blue_moves": sum(m.side == "blue" for m in self.moves),
                "injects": sum(m.side == "inject" for m in self.moves),
                "fallbacks": sum(m.fallback for m in self.moves),
                "llm_calls": sum(m.llm_calls for m in self.moves),
                "llm_requests": sum(m.llm_requests for m in self.moves),
                "jev_calls": sum(m.selection.get("jev_calls", 0) for m in self.moves),
                "jev_ms": round(sum(m.selection.get("request_ms", 0) for m in self.moves), 1),
                "total_ms": round(((self._ended or time.perf_counter()) - self._started) * 1000, 1),
                "llm_ms": round(sum(m.llm_ms for m in self.moves), 1),
                "db_ms": round(sum(m.db_ms for m in self.moves), 1), "file": self.path.stem,
                "strategic": self.strategic, "cumulative_loss": round(self.cumulative_loss, 1),
                "average_loss_pct": round(self.cumulative_loss / duration, 1) if duration else 0,
                "round_scores": self.round_scores,
                "objective_met": self.state == "done" and len(self.round_scores) == self.rounds
                                 and all(r["objective_met"] for r in self.round_scores),
                **(self.board.details(self.head) if self.strategic and self.moves else {})}

    def to_file(self) -> dict:
        return {"id": self.id, "created": self.events[0]["at"] if self.events else _now_iso(),
                "base_branch": self.base, "base_actions": self.base_actions,
                "base_loss_pct": _pct(self.base_loss), "rounds": self.rounds, "status": self.state,
                "model": getattr(self.llm, "model", None), "moves": [m.as_dict() for m in self.moves],
                "events": self.events, "summary": self.summary()}

    # ------------------------------------------------------------------ events + persistence

    def _set_state(self, state: str, emit: bool = True) -> None:
        self.state = state
        if emit:
            self._emit("status", {"state": state})

    def _emit(self, kind: str, data: dict) -> None:
        with self._emit_lock:
            self.events.append({"type": kind, "t": round(time.perf_counter() - self._started, 3),
                                "at": _now_iso(), "data": data})
            self._save()
        self._emit_cb(kind, data)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_file(), indent=1, default=str))
            tmp.replace(self.path)
        except OSError as exc:  # persistence must never kill a live match
            log.error("could not save match %s: %s", self.id, exc)


def _without(opts: dict, banned: str | list[str] | None) -> dict:
    """Options minus one action kind (the candidates, the default and its alternates)."""
    if not banned:
        return opts
    bans = {banned} if isinstance(banned, str) else set(banned)
    keep = [s for s in [opts.get("fallback"), *opts.get("alternates", [])] if s and s.get("action") not in bans]
    out = {**opts, "fallback": keep[0] if keep else None, "alternates": keep[1:], "not_allowed_this_turn": banned}
    if "deep_candidates" in opts:
        out["deep_candidates"] = [c for c in opts["deep_candidates"] if c.get("action") not in bans]
    return out


# ---------------------------------------------------------------------- replay


def load_match(name: str, directory: Path = MATCHES_DIR) -> dict:
    path = match_path(name, directory)
    if not path.exists():
        raise FileNotFoundError(f"no saved match {path.name}")
    return json.loads(path.read_text())


def list_matches(directory: Path = MATCHES_DIR) -> list[dict]:
    out = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skipping unreadable match %s: %s", path.name, exc)
            continue
        summary = data.get("summary", {})
        out.append({"file": path.stem, "id": data.get("id"), "created": data.get("created"),
                    "base_branch": data.get("base_branch"), "rounds": data.get("rounds"),
                    "status": data.get("status"), "moves": len(data.get("moves", [])),
                    "final_loss_pct": summary.get("final_loss_pct"), "model": data.get("model")})
    return out


def replay(data: dict, board: Board, emit: Emit, speed: float = 1.0, stop: threading.Event | None = None,
           sleep: Callable[[float], None] = time.sleep) -> dict:
    """Play a saved match back with its original event timing and NO LLM calls. Branches are rebuilt from
    the recorded edits (TuringDB still does the work), so the map, diffs and losses are live."""
    if speed <= 0:
        raise ValueError("speed must be > 0")
    stop = stop or threading.Event()
    base = str(data.get("base_branch", "main"))
    mapping = {"main": "main"}
    if base != "main":
        mapping[base] = board.rebuild(f"Replay base (was #{base})", data.get("base_actions", []))
    started = time.perf_counter()
    for ev in data.get("events", []):
        if stop.is_set():
            emit("match_done", {"status": "stopped", "replay": True, "summary": data.get("summary", {})})
            return {"status": "stopped", "branches": mapping}
        payload = _remap(ev["type"], ev.get("data", {}), board, mapping)  # rebuild overlaps the wait
        wait = ev.get("t", 0) / speed - (time.perf_counter() - started)
        if wait > 0:
            sleep(wait)
        emit(ev["type"], {**payload, "replay": True})
    return {"status": "done", "branches": mapping}


def _fresh_effects(board: Board, move: dict, parent: str, built: str) -> dict:
    """Recompute the map payload on the rebuilt branches (recordings made before an effects fix replay
    with the current map choreography). Falls back to what was recorded."""
    try:
        fx = board.effects(move["side"], parent, built, move["actions"])
    except Exception as exc:  # the map payload must never stop a replay
        log.warning("replay: keeping recorded map effects for %s (%s)", move.get("label"), exc)
        return {}
    return {"targets": fx.get("targets", []), "arcs": fx.get("arcs", [])}


def _remap(kind: str, data: dict, board: Board, mapping: dict[str, str]) -> dict:
    if kind == "match_started":
        return {**data, "base_branch": mapping.get(str(data.get("base_branch")), data.get("base_branch"))}
    if kind in ("move", "inject"):
        move = data if kind == "move" else data["move"]
        parent = mapping.get(str(move["parent_id"]), str(move["parent_id"]))
        built = board.stack(move["side"], move["label"], parent, move["actions"])
        mapping[str(move["branch_id"])] = built
        new_move = {**move, "branch_id": built, "parent_id": parent, **_fresh_effects(board, move, parent, built)}
        return new_move if kind == "move" else {**data, "branch": built, "move": new_move}
    if kind == "match_done":
        summary = data.get("summary", {})
        head = mapping.get(str(summary.get("head")), summary.get("head"))
        return {**data, "summary": {**summary, "head": head}}
    if "head" in data:
        return {**data, "head": mapping.get(str(data["head"]), data["head"])}
    return data


# ---------------------------------------------------------------------- CLI (thin wrapper)


def main() -> None:
    import argparse

    from agents.match_board import LabBoard, scenario_injector
    from agents.orchestrator import Lab

    parser = argparse.ArgumentParser(description="Turn-based red-vs-blue wargame on TuringDB branches")
    parser.add_argument("--base", default="main", help="base branch: main or a scenario change id")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--classic", action="store_true", help="play the original instant-recovery rules")
    parser.add_argument("--seed", type=int, default=7, help="reproducible midpoint congestion event")
    parser.add_argument("--inject", action="append", default=[],
                        help='ROUND:TEXT - queue an event before ROUND, e.g. 2:"the Liverpool port is closed"')
    parser.add_argument("--save-as", help="file name under matches/ (default: the match id)")
    parser.add_argument("--replay", help="replay matches/<name>.json instead of playing")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    lab = Lab.create()
    board = LabBoard(lab.branches)
    if args.replay:
        replay(load_match(args.replay), board, _print, speed=args.speed)
        return
    pending = [(int(r), t) for r, _, t in (s.partition(":") for s in args.inject)]
    match: Match | None = None

    def emit(kind: str, data: dict) -> None:
        _print(kind, data)
        if match is not None and kind in ("match_started", "round_done"):
            upcoming = data.get("round", 0) + 1
            for item in [p for p in pending if p[0] == upcoming]:
                match.inject(item[1])
                pending.remove(item)

    match = Match(board, args.base, args.rounds, llm=lab.llm, injector=scenario_injector(lab), emit=emit,
                  save_as=args.save_as, strategic=not args.classic, seed=args.seed)
    print(json.dumps(match.run(), indent=2))


def _print(kind: str, data: dict) -> None:
    print(kind, json.dumps(data, default=str)[:300], flush=True)


if __name__ == "__main__":
    main()
