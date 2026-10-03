"""The branch lab: the agents' search space.

Every attack, countermeasure and scenario is a TuringDB change (branch) built on main. The lab opens a
change, applies one hypothesis inside it, evaluates the supply-chain impact on that branch, and keeps the
branch so strategies can be compared with diffs. main is never modified.

A `(:AgentBranch {...})` marker node records each branch's role, label and parent, so the lab (and the
OpsMap UI) can describe branches, and so a ledger can be rebuilt after a server restart.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field

from api.backends.turing_session import Session, node_id_literal, string_literal
from api.refs import Ref
from api.support import Stopwatch

from agents.impact import Demand, Impact, evaluate, load_demand
from agents.runtime import Graph

log = logging.getLogger("agents.branches")
MARKER = "AgentBranch"


@dataclass
class BranchRecord:
    change_id: str
    role: str  # "threat" | "defence" | "scenario"
    label: str
    parent: str  # "main" or a change id this branch was stacked on
    spec: dict  # the hypothesis (actions applied), replayable after a restart
    loss: float | None = None
    baseline_loss: float | None = None
    summary: dict = field(default_factory=dict)
    note: str = ""

    @property
    def delta_loss(self) -> float | None:
        if self.loss is None or self.baseline_loss is None:
            return None
        return self.loss - self.baseline_loss


class BranchExists(ValueError):
    pass


class BranchLab:
    """Opens, applies to, evaluates and compares branches. Thread-safe; writes are serialised."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self._lock = threading.RLock()
        self._ledger: dict[str, BranchRecord] = {}
        self._demand: Demand | None = None
        self._baseline: Impact | None = None
        graph.supervisor.on_restart(self._replay)

    # ------------------------------------------------------------------ baseline

    def ensure_ready(self) -> None:
        self.graph.supervisor.ensure_running()
        if self._demand is None:
            with self._lock:
                if self._demand is None:
                    main = self.graph.session("main")
                    self._demand = load_demand(main)
                    self._baseline = evaluate(main, self._demand)
                    log.info("baseline loss %.1f%%", 100 * self._baseline.loss)

    @property
    def demand(self) -> Demand:
        assert self._demand is not None, "call ensure_ready() first"
        return self._demand

    @property
    def baseline(self) -> Impact:
        assert self._baseline is not None, "call ensure_ready() first"
        return self._baseline

    def records(self) -> list[BranchRecord]:
        return list(self._ledger.values())

    def record(self, change_id: str) -> BranchRecord | None:
        return self._ledger.get(str(change_id))

    def spec_of(self, change_id: str) -> dict:
        """A branch's replayable spec: from the ledger, else from its (:AgentBranch) marker in TuringDB
        (a branch built by an earlier process). Raises ValueError for unknown or non-agent changes."""
        change_id = str(change_id)
        if change_id == "main":
            return {"actions": []}
        rec = self._ledger.get(change_id)
        if rec is not None:
            return rec.spec
        if change_id not in self.graph.change_ids():
            raise ValueError(f"unknown branch {change_id}")
        s = self.graph.session(change_id)
        if MARKER not in s.labels:
            raise ValueError(f"branch {change_id} was not built by an agent; its edits cannot be replayed")
        frame = s.q(f"MATCH (m:{MARKER}) RETURN m.role AS role, m.label AS label, m.parent AS parent, "
                    "m.spec AS spec")
        if frame.empty:
            raise ValueError(f"branch {change_id} has no {MARKER} marker")
        role, label, parent, spec = frame.iloc[0]
        parsed = parse_marker_spec(str(spec))
        with self._lock:  # adopt it so later reads skip TuringDB
            self._ledger[change_id] = BranchRecord(change_id=change_id, role=str(role), label=str(label),
                                                   parent=str(parent), spec=parsed)
        return parsed

    # ------------------------------------------------------------------ building a branch

    def open_branch(self, role: str, label: str, spec: dict, parent: str = "main") -> tuple[Session, BranchRecord]:
        self.ensure_ready()
        with self._lock:
            # TuringDB 1.37 cannot open a change on top of a change, so every branch is cut from main.
            # `parent` is lineage only: a defence branch replays its threat's actions before its own, so it
            # is an independent, diff-comparable state (main + attack + countermeasures).
            client = self.graph.backend._session(Ref("main"), Stopwatch("turingdb")).client
            change = str(client.new_change())
            s = self.graph.session(change)
            marker = {"role": role, "label": label, "parent": parent, "spec": json.dumps(spec, sort_keys=True)}
            props = ", ".join(f"{k}: {string_literal(str(v))}" for k, v in marker.items())
            s.q(f"CREATE (:{MARKER} {{{props}}})")
            s.q("COMMIT")
            rec = BranchRecord(change_id=change, role=role, label=label, parent=parent, spec=spec,
                               baseline_loss=self.baseline.loss)
            self._ledger[change] = rec
            return s, rec

    def evaluate_branch(self, change_id: str) -> Impact:
        """Compute projected loss on a branch and cache it in the ledger."""
        self.ensure_ready()
        s = self.graph.session(str(change_id))
        imp = evaluate(s, self.demand)
        rec = self._ledger.get(str(change_id))
        if rec is not None:
            rec.loss = imp.loss
            rec.summary = imp.summary()
        return imp

    def discard(self, change_id: str) -> None:
        with self._lock:
            self.graph.session(str(change_id)).q("CHANGE DELETE")
            self._ledger.pop(str(change_id), None)

    # ------------------------------------------------------------------ primitive edits (inside a branch)

    def _resolve_plant(self, s: Session, gppd_or_id: str) -> int:
        if gppd_or_id.isdigit():
            return node_id_literal(gppd_or_id)
        frame = s.q(f"MATCH (p:PowerPlant) WHERE p.gppd_idnr = {string_literal(gppd_or_id)} RETURN p")
        if frame.empty:
            raise ValueError(f"no PowerPlant with gppd_idnr {gppd_or_id!r}")
        return int(frame["p"].iloc[0])

    def _resolve(self, s: Session, label: str, key_prop: str, key: str) -> int:
        if key.isdigit():
            return node_id_literal(key)
        # Supplier keys are source-prefixed in theatre (supply_chain:SUPnnn); accept the bare id too.
        candidates = [key]
        if label == "Supplier" and ":" not in key:
            candidates += [f"supply_chain:{key}", f"logistics_risk:{key}"]
        for cand in candidates:
            frame = s.q(f"MATCH (n:{label}) WHERE n.{key_prop} = {string_literal(cand)} RETURN n")
            if not frame.empty:
                return int(frame["n"].iloc[0])
        raise ValueError(f"no {label} with {key_prop} {key!r}")

    def delete_node(self, s: Session, node_id: int) -> None:
        s.q(f"MATCH (n) WHERE n = {node_id} DETACH DELETE n")
        s.q("COMMIT")

    def protect_node(self, s: Session, node_id: int, how: str) -> None:
        """Air-defence priority: a flag, not a deletion. A threat branch honours it by refusing to strike."""
        s.q(f"MATCH (n) WHERE n = {node_id} SET n.protected = true, n.protection = {string_literal(how)}")
        s.q("COMMIT")

    def add_edge(self, s: Session, src: int, dst: int, rel: str, props: dict | None = None,
                 commit: bool = True) -> None:
        extra = {"synthetic": "true", "agent_added": "true", **(props or {})}
        body = ", ".join(f"{k}: {_literal(v)}" for k, v in extra.items())
        s.q(f"MATCH (a), (b) WHERE a = {src} AND b = {dst} CREATE (a)-[:{rel} {{{body}}}]->(b)")
        if commit:
            s.q("COMMIT")

    def is_protected(self, s: Session, node_id: int) -> bool:
        if "protected" not in s.property_types:
            return False
        frame = s.q(f"MATCH (n) WHERE n = {node_id} AND n.protected = true RETURN n")
        return not frame.empty

    # ------------------------------------------------------------------ diffs

    def diff_impacts(self, change_a: str, change_b: str) -> dict:
        """Diff two branches (or 'main') by their impact profile — the meaningful diff for strategy."""
        self.ensure_ready()
        ia = self.baseline if change_a == "main" else self.evaluate_branch(change_a)
        ib = self.baseline if change_b == "main" else self.evaluate_branch(change_b)
        sites = sorted(set(ia.site_loss) | set(ib.site_loss))
        return {
            "a": change_a, "b": change_b,
            "loss_a_pct": round(100 * ia.loss, 1), "loss_b_pct": round(100 * ib.loss, 1),
            "loss_delta_pct": round(100 * (ib.loss - ia.loss), 1),
            "per_site": {site: {"a": round(100 * ia.site_loss.get(site, 0), 1),
                                "b": round(100 * ib.site_loss.get(site, 0), 1)} for site in sites},
            "sites_down_a": ia.sites_down, "sites_down_b": ib.sites_down,
            "critical_parts_a": len(ia.critical_parts_unavailable),
            "critical_parts_b": len(ib.critical_parts_unavailable),
        }

    def diff_graph(self, change_a: str, change_b: str) -> dict:
        """Node-level TuringDB diff (added / removed / status-changed), reusing the OpsMap diff machinery."""
        self.ensure_ready()
        resp = self.graph.backend.diff(_ref(change_a), _ref(change_b))
        return {
            "a": change_a, "b": change_b,
            "added": [n.name for n in resp.added], "removed": [n.name for n in resp.removed],
            "changed": [{"name": c.node.name, "fields": {k: list(v) for k, v in c.fields.items()}}
                        for c in resp.changed],
            "latency_ms": resp.latency_ms,
        }

    # ------------------------------------------------------------------ restart recovery

    def _replay(self) -> None:
        """After a server restart every in-memory change is gone; rebuild each branch from its spec."""
        with self._lock:
            old = list(self._ledger.values())
            self._ledger.clear()
            self._demand = self._baseline = None
            if not old:
                return
            log.warning("replaying %d agent branches after restart", len(old))
            from agents.actions import replay_branch  # late import avoids a cycle

            time.sleep(1)
            for rec in sorted(old, key=lambda r: r.parent != "main"):  # parents before stacked children
                try:
                    replay_branch(self, rec)
                except Exception as exc:
                    log.error("could not replay branch %s (%s): %s", rec.change_id, rec.label, exc)


def _literal(value) -> str:
    """A Cypher literal: numbers stay numeric (TuringDB 3.0 rejects a String where the property is a Double),
    'true'/'false' and bools are booleans, everything else a quoted string."""
    if isinstance(value, bool) or value in ("true", "false"):
        return "true" if value in (True, "true") else "false"
    if isinstance(value, (int, float)):
        return repr(float(value))
    return string_literal(str(value))


def parse_marker_spec(stored: str) -> dict:
    """Read back a spec written into a marker. `string_literal` swaps quote characters for typographic ones
    (TuringDB string escaping is undocumented), so the stored JSON has ” and ’ where " and ' were."""
    return json.loads(stored.replace("”", '"').replace("’", "'"))


def _ref(change: str) -> Ref:
    return Ref("main") if change == "main" else Ref(str(change))
