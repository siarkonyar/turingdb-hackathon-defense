"""Tool builders shared by the agents. Every tool is grounded in TuringDB: reads go through the Cypher
guard, writes go through the branch lab, so a branch is the only place an agent can change state."""

from __future__ import annotations

from typing import Any

from agents.actions import apply_action
from agents.branches import BranchLab
from agents.engine import Tool
from agents.guard import UnsafeQuery, check_read_query


def _rows(frame, limit: int = 60) -> list[dict]:
    return frame.head(limit).to_dict("records")


def schema_tool(lab: BranchLab) -> Tool:
    def run() -> dict:
        s = lab.graph.session("main")
        return {"labels": sorted(s.labels), "edge_types": sorted(s.q("CALL db.edgeTypes()").iloc[:, 0].astype(str)),
                "properties": list(s.property_types)}
    return Tool("schema", "List node labels, edge types and property names of the graph.", run)


def query_tool(lab: BranchLab) -> Tool:
    def run(cypher: str, branch: str = "main") -> dict:
        try:
            safe = check_read_query(cypher)
        except UnsafeQuery as exc:
            return {"error": str(exc)}
        frame, ms = lab.graph.guarded_query(branch, safe)
        return {"cypher": safe, "rows": _rows(frame), "row_count": len(frame), "exec_ms": ms}
    return Tool("query", "Run ONE read-only Cypher query (single linear MATCH path, auto-LIMITed). "
                "Use it to explore entities and relationships.", run,
                {"cypher": "the Cypher read query", "branch": "branch id to read, or 'main' (default)"})


def impact_tool(lab: BranchLab) -> Tool:
    def run(branch: str = "main") -> dict:
        imp = lab.baseline if branch == "main" else lab.evaluate_branch(branch)
        return {"branch": branch, **imp.summary()}
    return Tool("impact", "Projected supply-chain loss on a branch (or 'main'): loss %, per-site loss, "
                "sites/suppliers/parts down. This is the objective to optimise.", run,
                {"branch": "branch id or 'main'"})


def branches_tool(lab: BranchLab, role: str | None = None) -> Tool:
    def run() -> list[dict]:
        out = []
        for r in lab.records():
            if role and r.role != role:
                continue
            out.append({"change_id": r.change_id, "role": r.role, "label": r.label, "parent": r.parent,
                        "loss_pct": None if r.loss is None else round(100 * r.loss, 1),
                        "attacks": _attack_count(r.spec)})
        return out
    return Tool("list_branches", "List the branches explored so far with their loss and attack count.", run)


def diff_tool(lab: BranchLab) -> Tool:
    def run(a: str, b: str) -> dict:
        return {"impact": lab.diff_impacts(a, b), "graph": lab.diff_graph(a, b)}
    return Tool("diff", "Diff two branches (or 'main'): impact diff (loss before/after, per site) and "
                "graph diff (nodes added/removed/changed).", run,
                {"a": "first branch id or 'main'", "b": "second branch id or 'main'"})


def _attack_count(spec: dict) -> int:
    return sum(1 for a in spec.get("actions", []) if a.get("action", "").startswith(("strike", "cut", "wipe")))


def build_branch(lab: BranchLab, role: str, label: str, actions: list[dict], parent: str = "main") -> dict:
    """Open a branch, apply an action list, evaluate it, and return a compact result for the model."""
    if not isinstance(actions, list) or not actions:
        return {"error": "actions must be a non-empty list of {action, args} steps"}
    spec = {"actions": actions, "parent": parent}
    s, rec = lab.open_branch(role, label, spec, parent=parent)
    applied = []
    for step in actions:
        if not isinstance(step, dict) or "action" not in step:
            lab.discard(rec.change_id)
            return {"error": f"each step needs an 'action' key; got {step!r}"}
        try:
            applied.append(apply_action(lab, s, step["action"], step.get("args", {})))
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            lab.discard(rec.change_id)
            return {"error": f"action {step.get('action')!r} failed: {msg}"}
    imp = lab.evaluate_branch(rec.change_id)
    base = lab.baseline.loss
    return {
        "change_id": rec.change_id, "label": label, "applied": applied,
        "loss_pct": round(100 * imp.loss, 1), "baseline_pct": round(100 * base, 1),
        "delta_pct": round(100 * (imp.loss - base), 1), "attacks": _attack_count(spec),
        "summary": imp.summary(),
    }
