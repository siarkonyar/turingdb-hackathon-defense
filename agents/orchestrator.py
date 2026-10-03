"""Autonomous red-vs-blue orchestration. No operator intervention: the supervisor starts and heals the
TuringDB server, the agents build and keep their own branches, and the run ends with a branch comparison.

    uv run python -m agents.orchestrator                 # threat -> defence, print the comparison
    uv run python -m agents.orchestrator --json out.json # also dump the full traces + branch ledger
    uv run python -m agents.orchestrator --scenario "A catastrophic event has destroyed everything \
across Manchester. How would this affect the rest of the city and its connected infrastructure?"
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field

from agents.branches import BranchLab
from agents.config import load_agent_settings
from agents.defence import run_defence
from agents.engine import StepListener, Trace
from agents.llm import FeatherlessLLM, LLMUnavailable
from agents.runtime import Graph, Supervisor
from agents.scenario import run_scenario
from agents.threat import run_threat

log = logging.getLogger("agents.orchestrator")


@dataclass
class Lab:
    settings: object
    llm_or_none: FeatherlessLLM | None  # None when the key is unset: replay and branch work still run
    graph: Graph
    branches: BranchLab
    llm_error: str | None = None

    @classmethod
    def create(cls) -> "Lab":
        cfg = load_agent_settings()
        sup = Supervisor(cfg.turingdb_host, cfg.graph, cfg.turing_dir, autostart=cfg.autostart)
        sup.ensure_running()
        graph = Graph(cfg.turingdb_host, cfg.graph, sup, timeout_s=cfg.query_timeout_s)
        branches = BranchLab(graph)
        branches.ensure_ready()
        try:
            llm, error = FeatherlessLLM(cfg), None
        except LLMUnavailable as exc:
            llm, error = None, str(exc)
            log.warning("LLM unavailable (%s); only replay and branch operations will work", exc)
        return cls(cfg, llm, graph, branches, error)

    @property
    def llm(self) -> FeatherlessLLM:
        if self.llm_or_none is None:
            raise LLMUnavailable(self.llm_error or "FEATHERLESS_API_KEY is not set")
        return self.llm_or_none


@dataclass
class RedBlueResult:
    baseline_pct: float
    threat_branch: str
    threat_loss_pct: float
    defence_branch: str
    defence_loss_pct: float
    reduction_pct: float
    headline: str
    threat_trace: Trace
    defence_trace: Trace
    impact_diff: dict
    graph_diff: dict

    def as_dict(self) -> dict:
        return {
            "baseline_pct": self.baseline_pct, "threat_branch": self.threat_branch,
            "threat_loss_pct": self.threat_loss_pct, "defence_branch": self.defence_branch,
            "defence_loss_pct": self.defence_loss_pct, "reduction_pct": self.reduction_pct,
            "headline": self.headline, "impact_diff": self.impact_diff, "graph_diff": self.graph_diff,
            "threat_trace": self.threat_trace.as_dict(), "defence_trace": self.defence_trace.as_dict(),
        }


def _pick_worst(lab: BranchLab, trace: Trace) -> str:
    """The threat's chosen worst branch, else the highest-loss threat branch actually built."""
    chosen = (trace.result or {}).get("worst_branch")
    if chosen and lab.record(str(chosen)):
        return str(chosen)
    threat = [r for r in lab.records() if r.role == "threat" and r.loss is not None]
    if not threat:
        raise RuntimeError("threat agent built no evaluated branch")
    return max(threat, key=lambda r: r.loss).change_id


def _countermeasures(lab: BranchLab, defence_branch: str, trace: Trace) -> list[str]:
    """Countermeasure action list for the chosen defence branch (from its spec minus the replayed attack)."""
    rec = lab.record(str(defence_branch))
    if rec is not None:
        attack = {json.dumps(a, sort_keys=True) for a in (lab.record(rec.parent).spec.get("actions", [])
                                                          if lab.record(rec.parent) else [])}
        return [a.get("action", "") for a in rec.spec.get("actions", [])
                if json.dumps(a, sort_keys=True) not in attack and a.get("action", "")]
    return [c.get("action", "") if isinstance(c, dict) else str(c)
            for c in (trace.result or {}).get("countermeasures", [])]


def _summarise(countermeasures: list[str]) -> str:
    from collections import Counter

    pretty = {"add_backup_supplier": "backup supplier", "reroute_supplier": "alternative route",
              "restore_power": "alternative power feed", "prioritise_air_defence": "air-defence priority",
              "backup_all_affected_parts": "all-affected-parts backup programme"}
    counts = Counter(countermeasures)
    parts = [f"{n} {pretty.get(a, a)}{'s' if n > 1 else ''}" for a, n in counts.most_common()]
    return ", ".join(parts)


def run_red_blue(lab: Lab, threat_steps: int = 16, defence_steps: int = 16,
                 on_step: StepListener | None = None) -> RedBlueResult:
    threat_trace = run_threat(lab.branches, lab.llm, max_steps=threat_steps, on_step=on_step)
    worst = _pick_worst(lab.branches, threat_trace)
    threat_loss = lab.branches.evaluate_branch(worst).loss
    log.info("threat worst branch %s at %.1f%% loss", worst, 100 * threat_loss)

    defence_trace = run_defence(lab.branches, lab.llm, worst, max_steps=defence_steps, on_step=on_step)
    # Compare the defence branches and select the best (lowest projected loss) countermeasure set found -
    # the honest "result" of the exploration, not just whichever branch the agent named last.
    defences = [r for r in lab.branches.records() if r.role == "defence" and r.loss is not None
                and r.spec.get("parent") == worst]
    if not defences:
        raise RuntimeError("defence agent built no evaluated branch")
    best = min(defences, key=lambda r: r.loss)
    chosen = (defence_trace.result or {}).get("defence_branch")
    # honour the agent's pick only if it is at least as good as the best explored
    if chosen and lab.branches.record(str(chosen)):
        crec = lab.branches.record(str(chosen))
        if crec.role == "defence" and crec.loss is not None and crec.loss <= best.loss + 1e-9:
            best = crec
    defence_branch = best.change_id
    defence_loss = lab.branches.evaluate_branch(defence_branch).loss

    impact_diff = lab.branches.diff_impacts(worst, defence_branch)
    graph_diff = lab.branches.diff_graph(worst, defence_branch)
    reduction = 100 * (threat_loss - defence_loss)
    cms = _countermeasures(lab.branches, defence_branch, defence_trace)
    summary = _summarise(cms)
    noun = "countermeasure" if len(cms) == 1 else "countermeasures"
    headline = (f"{len(cms)} {noun} reduce the projected loss from "
                f"{100 * threat_loss:.0f}% to {100 * defence_loss:.0f}%"
                + (f" ({summary})" if summary else ""))
    return RedBlueResult(
        baseline_pct=round(100 * lab.branches.baseline.loss, 1), threat_branch=worst,
        threat_loss_pct=round(100 * threat_loss, 1), defence_branch=defence_branch,
        defence_loss_pct=round(100 * defence_loss, 1), reduction_pct=round(reduction, 1),
        headline=headline, threat_trace=threat_trace, defence_trace=defence_trace,
        impact_diff=impact_diff, graph_diff=graph_diff)


def run_scenario_question(lab: Lab, question: str, steps: int = 18, on_step: StepListener | None = None) -> dict:
    trace = run_scenario(lab.branches, lab.llm, question, max_steps=steps, on_step=on_step)
    result = trace.result or {}
    branch = result.get("branch")
    out = {"question": question, "result": result, "trace": trace.as_dict()}
    if branch and lab.branches.record(str(branch)):
        out["impact_diff"] = lab.branches.diff_impacts("main", str(branch))
        out["branch"] = str(branch)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", help="run the scenario agent on this natural-language question")
    parser.add_argument("--threat-steps", type=int, default=16)
    parser.add_argument("--defence-steps", type=int, default=16)
    parser.add_argument("--json", help="write the full result/traces to this file")
    parser.add_argument("--keep", action="store_true", help="keep branches after the run (default: keep)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    lab = Lab.create()
    if lab.llm_or_none is None:
        raise SystemExit(f"Featherless unavailable: {lab.llm_error}")

    if args.scenario:
        out = run_scenario_question(lab, args.scenario)
        print("\n=== SCENARIO ===")
        print(out["result"].get("explanation") or out["result"].get("headline") or out["result"])
        if "impact_diff" in out:
            print("supply-chain loss on scenario branch:", out["impact_diff"]["loss_b_pct"], "%")
        payload = out
    else:
        res = run_red_blue(lab, args.threat_steps, args.defence_steps)
        print("\n=== RED vs BLUE ===")
        print("baseline loss:   ", res.baseline_pct, "%")
        print("threat branch:   ", res.threat_branch, "->", res.threat_loss_pct, "%")
        print("defence branch:  ", res.defence_branch, "->", res.defence_loss_pct, "%")
        print("HEADLINE:        ", res.headline)
        print("model:           ", lab.llm.model)
        print("Featherless calls:", lab.llm.usage.calls)
        payload = res.as_dict()

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print("wrote", args.json)


if __name__ == "__main__":
    main()
