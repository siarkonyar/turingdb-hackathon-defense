"""Disruption and recovery branches on the live `dover` graph. Main is never written.

TuringDB has no change-on-change, so every branch is cut from main and replays its lineage:
- disruption branch: the event (Scenario active, targets disabled/destroyed) + affected-facility flags;
- recovery branch:   the same event replayed first, then the plan (options active, allocation records,
                     end-of-window facility states).
Each branch carries `(:ResilienceBranch {role, scenario_id, label, parent, spec})`; `spec` is base64url JSON
holding the event and the typed actions, so `replay()` rebuilds an equivalent branch and `_verify()` re-measures
the plan the branch itself stores.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from agents.resilience.exercises import Exercise, get_exercise
from agents.resilience.explain import Comparison, Hit
from agents.resilience.network import Network, from_session
from agents.resilience.plans import Action, Plan
from agents.resilience.simulate import Outcome, simulate

log = logging.getLogger("agents.resilience.lab")
SPEC_VERSION = 1
CHUNK = 150  # OR-chain length per write (TuringDB rejects expressions nested deeper than 256)
CREATE_BATCH = 40
MARKER = "ResilienceBranch"
STATES = ("restored", "relocated", "improved", "residual")


def encode(spec: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(spec, sort_keys=True).encode()).decode()


def decode(text: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(text.encode()).decode())


def _lit(value: str) -> str:
    from api.backends.turing_session import string_literal

    return string_literal(value)


def _chunks(items: Sequence[str], size: int = CHUNK) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _where_eid(var: str, eids: Sequence[str]) -> str:
    return "(" + " OR ".join(f"{var}.entity_id = {_lit(e)}" for e in eids) + ")"


def plan_spec(plan: Plan) -> dict:
    return {"plan_id": plan.plan_id, "title": plan.title, "summary": plan.summary,
            "actions": [{**asdict(a), "loads": list(a.loads)} for a in plan.actions]}


def plan_from_spec(spec: dict) -> Plan:
    actions = tuple(Action(a["kind"], a["target"], a["option_id"], tuple(a.get("loads") or ()), a.get("scope", "all"))
                    for a in spec["actions"])
    return Plan(spec["plan_id"], spec["title"], spec.get("summary", ""), actions)


@dataclass(frozen=True)
class BranchRecord:
    branch: str
    role: str  # disruption | recovery
    scenario_id: str
    plan_id: str | None
    parent: str
    verified: bool  # read back from the branch and re-measured to the same figures

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BranchState:
    spec: dict
    scenario_active: bool
    targets_down: frozenset[str]
    active_options: frozenset[str]
    allocations: int
    states: dict[str, int]  # resilience_state -> count


class ResilienceLab:
    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self._lock = threading.Lock()
        self._net: Network | None = None

    # ------------------------------------------------------------------ reads

    def _session(self, ref: str) -> Any:
        from api.backends.turing import ENGINE
        from api.refs import Ref
        from api.support import Stopwatch

        return self.backend.session(Ref(ref), Stopwatch(ENGINE))

    def network(self) -> Network:
        if self._net is None:
            self._net = from_session(self._session("main"))
        return self._net

    def main_head(self) -> str:
        return self._session("main").head()

    def timed(self, cypher: str) -> tuple[Any, list[Any]]:
        """Run one read on main; returns the frame and the per-query TuringDB timings."""
        s = self._session("main")
        return s.q(cypher), list(s.sw.traces)

    def read_state(self, branch: str) -> BranchState:
        s = self._session(branch)
        spec = decode(str(s.q(f"MATCH (m:{MARKER}) RETURN m.spec AS spec")["spec"].iloc[0]))
        down: set[str] = set()
        for part in _chunks(spec["event"]["targets"]):
            frame = s.q(f"MATCH (n) WHERE {_where_eid('n', part)} AND (n.status = 'disabled' OR "
                        "n.status = 'destroyed') RETURN n.entity_id AS e")
            down |= {str(e) for e in frame["e"]}
        active = s.q(f"MATCH (x:Scenario) WHERE x.entity_id = {_lit(spec['scenario_id'])} RETURN x.active AS a")
        options = s.q("MATCH (r:RecoveryOption) WHERE r.active = true RETURN r.entity_id AS e")
        allocations = int(s.q("MATCH (a:Allocation) RETURN count(a) AS n").iloc[0, 0]) if "Allocation" in s.labels else 0
        states: dict[str, int] = {}
        if "resilience_state" in s.property_types:
            cond = " OR ".join(f"n.resilience_state = '{st}'" for st in STATES)
            frame = s.q(f"MATCH (n) WHERE {cond} RETURN n.resilience_state AS st, count(n) AS c")
            states = {str(r["st"]): int(r["c"]) for r in frame.to_dict("records")}
        return BranchState(spec, bool(active["a"].iloc[0]), frozenset(down),
                           frozenset(str(e) for e in options["e"]), allocations, states)

    # ------------------------------------------------------------------ writes

    def _new_branch(self) -> Any:
        change = str(self._session("main").client.new_change())
        return self._session(change)

    def _marker(self, s: Any, role: str, ex: Exercise, label: str, parent: str, spec: dict) -> None:
        s.q(f"CREATE (:{MARKER} {{role: {_lit(role)}, scenario_id: {_lit(ex.scenario_id)}, label: {_lit(label)}, "
            f"parent: {_lit(parent)}, spec: {_lit(encode(spec))}}})")

    def _apply_event(self, s: Any, ex: Exercise, targets: Sequence[str]) -> None:
        s.q(f"MATCH (x:Scenario) WHERE x.entity_id = {_lit(ex.scenario_id)} SET x.active = true")
        status = "destroyed" if ex.destroys else "disabled"
        for part in _chunks(sorted(targets)):
            s.q(f"MATCH (n) WHERE {_where_eid('n', part)} SET n.status = '{status}', n.ops_status = 'lost'")

    def _flag(self, s: Any, eids: Sequence[str], prop: str, value: str) -> None:
        for part in _chunks(sorted(eids)):
            s.q(f"MATCH (n) WHERE {_where_eid('n', part)} SET n.{prop} = {_lit(value)}")

    def _allocations(self, s: Any, rows: list[dict]) -> None:
        for i in range(0, len(rows), CREATE_BATCH):
            parts = []
            for r in rows[i:i + CREATE_BATCH]:
                fields = ", ".join(f"{k}: {_lit(v) if isinstance(v, str) else float(v)}" for k, v in r.items())
                parts.append(f"(:Allocation {{{fields}}})")
            s.q("CREATE " + ", ".join(parts))

    @staticmethod
    def _guard(s: Any, work: Any) -> None:
        try:
            work()
            s.q("COMMIT")
        except Exception:
            try:
                s.q("CHANGE DELETE")
            except Exception as exc:  # the original error matters more; log the cleanup failure
                log.error("could not delete change %s after a failed write: %s", s.ref.branch, exc)
            raise

    def disrupt(self, ex: Exercise, outcome: Outcome, hits: Sequence[Hit]) -> BranchRecord:
        """A branch holding only the event and the affected-facility flags of the measured cascade."""
        spec = {"version": SPEC_VERSION, "role": "disruption", "scenario_id": ex.scenario_id,
                "event": {"kind": ex.kind, "hours": ex.hours, "targets": sorted(outcome.initial)}, "plan": None}
        with self._lock:
            s = self._new_branch()

            def work() -> None:
                self._marker(s, "disruption", ex, f"{ex.title} (disruption)", "main", spec)
                self._apply_event(s, ex, spec["event"]["targets"])
                self._flag(s, [h.eid for h in hits if h.eid not in outcome.initial], "ops_status", "at_risk")
            self._guard(s, work)
        return self._verify(s.ref.branch, ex, None, outcome, "main")

    def recover(self, ex: Exercise, plan: Plan, outcome: Outcome, comparison: Comparison,
                parent: str) -> BranchRecord:
        """A new branch from main: the disruption replayed, then the plan and its allocation records."""
        spec = {"version": SPEC_VERSION, "role": "recovery", "scenario_id": ex.scenario_id,
                "event": {"kind": ex.kind, "hours": ex.hours, "targets": sorted(outcome.initial)},
                "plan": plan_spec(plan)}
        with self._lock:
            s = self._new_branch()

            def work() -> None:
                self._marker(s, "recovery", ex, f"{ex.title}: {plan.title}", parent, spec)
                self._apply_event(s, ex, spec["event"]["targets"])
                for part in _chunks(sorted(a.option_id for a in plan.actions)):
                    s.q(f"MATCH (r:RecoveryOption) WHERE {_where_eid('r', part)} SET r.active = true")
                self._allocations(s, allocation_rows(outcome))
                for state in STATES:
                    self._flag(s, [x.eid for x in comparison.states if x.state == state], "resilience_state", state)
                self._flag(s, [x.eid for x in comparison.states if x.state in ("improved", "residual")],
                           "ops_status", "at_risk")
            self._guard(s, work)
        return self._verify(s.ref.branch, ex, plan, outcome, parent)

    def replay(self, branch: str, outcome: Outcome, hits: Sequence[Hit] = (),
               comparison: Comparison | None = None) -> BranchRecord:
        """Rebuild a stored branch from its spec into a new branch from main (lineage replay)."""
        spec = self.read_state(branch).spec
        ex = get_exercise(spec["scenario_id"])
        if spec["role"] == "disruption":
            return self.disrupt(ex, outcome, hits)
        if comparison is None:
            raise ValueError("replaying a recovery branch needs its comparison")
        return self.recover(ex, plan_from_spec(spec["plan"]), outcome, comparison, branch)

    def _verify(self, branch: str, ex: Exercise, plan: Plan | None, expected: Outcome, parent: str) -> BranchRecord:
        """Read the branch back and re-measure the plan it stores; figures must match the pre-execution ones."""
        state = self.read_state(branch)
        stored = plan_from_spec(state.spec["plan"]) if state.spec.get("plan") else None
        ok = (state.scenario_active and state.targets_down == expected.initial
              and state.active_options == frozenset(a.option_id for a in (stored.actions if stored else ())))
        if ok and stored is not None:
            ok = simulate(self.network(), ex, stored).metrics == expected.metrics
        if not ok:
            log.error("branch %s did not verify against its measurement", branch)
        return BranchRecord(branch, state.spec["role"], ex.scenario_id, plan.plan_id if plan else None, parent, ok)

    def discard(self, branch: str) -> None:
        with self._lock:
            s = self._session(branch)
            if MARKER not in s.labels:
                raise ValueError(f"{branch} is not a resilience branch")
            s.q("CHANGE DELETE")


def allocation_rows(outcome: Outcome) -> list[dict]:
    """Replayable allocation records: what each action consumed and when it was ready."""
    p, rows = outcome.prepared, []
    for f in p.feeds:
        rows.append({"option_id": f.option_id, "kind": "generator", "source": f.stock, "target": ",".join(f.loads),
                     "quantity": float(f.generators), "unit": "generators", "ready_hours": f.ready_h,
                     "until_hours": f.until_h})
    released = outcome.consumption.stock_released_by_reserve
    for r in p.releases:
        rows.append({"option_id": r.option_id, "kind": "stock", "source": r.reserve, "target": r.service,
                     "quantity": float(released.get(r.reserve, 0.0)), "unit": "tonnes", "ready_hours": r.ready_h,
                     "until_hours": r.until_h})
    for t in p.transfers:
        rows.append({"option_id": t.option_id, "kind": t.kind, "source": t.provider, "target": t.receiver,
                     "quantity": float(t.people if t.kind == "programme" else t.tonnes_day),
                     "unit": "people" if t.kind == "programme" else "tonnes_per_day", "ready_hours": t.ready_h,
                     "until_hours": outcome.hours})
    for r in p.routes:
        rows.append({"option_id": r.option_id, "kind": "route", "source": r.route, "target": r.scope,
                     "quantity": float(outcome.consumption.route_tonnes.get(r.route, 0.0)), "unit": "tonnes",
                     "ready_hours": r.ready_h, "until_hours": outcome.hours})
    return rows
