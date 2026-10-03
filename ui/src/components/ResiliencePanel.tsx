import { useEffect, useRef } from "react";

import type { DisruptionView, RecoveryView } from "../api/types";
import { pct, tonnes } from "../lib/resilience";
import {
  askAssistant,
  askSuggestion,
  clearChat,
  loadExercises,
  setChatQuestion,
  setResilienceOpen,
  showEffects,
  showRecoveryPlan,
} from "../state/resilience";
import { useOps, type ChatEntry } from "../state/store";

const ACTION_LABELS: Record<string, string> = {
  inspect_exercise: "inspecting the impact",
  list_candidates: "listing feasible recovery plans",
  evaluate_plan: "measuring a plan",
  compare_plans: "comparing plans",
  execute_plan: "applying the chosen plan in a recovery branch",
  finish: "finishing",
};

function Disruption({ view }: { view: DisruptionView }) {
  const c = view.cascade;
  const side = useOps((s) => s.resilience.side);
  const latest = useOps((s) => s.resilience.disruption === view);
  return (
    <div className="chat__bot">
      <p>
        Disruption applied in branch #{view.branch.branch}. One {c.reach.depth_limit}-hop TuringDB query reached{" "}
        {c.reach.reached.toLocaleString("en-GB")} dependent nodes; {c.total_affected.toLocaleString("en-GB")}{" "}
        facilities, ports and routes lose service across {c.max_degree} dependency degrees. Essential demand falls to{" "}
        <strong>{pct(view.metrics.essential_fulfilment)}</strong> and {tonnes(view.metrics.cargo_unmet_t)} of cargo is
        not delivered.
      </p>
      {latest ? (
        <button type="button" className="btn btn--primary" onClick={showEffects} disabled={side === "effects"}>
          Show the effects
        </button>
      ) : null}
    </div>
  );
}

function Recovery({ view }: { view: RecoveryView }) {
  const d = view.decision;
  const chosen = view.candidates.find((c) => c.chosen);
  const open = useOps((s) => s.resilience.side === "recovery" && s.resilience.recovery === view);
  return (
    <div className="chat__bot">
      <p>
        Recovery plan ready: <strong>{chosen?.title ?? d.plan_id}</strong>, chosen from {view.candidates.length} measured
        plans and applied in recovery branch #{view.branch.branch}. Essential demand{" "}
        {pct(view.before.essential_fulfilment)} → <strong>{pct(view.after.essential_fulfilment)}</strong>, all demand{" "}
        {pct(view.before.overall_fulfilment)} → {pct(view.after.overall_fulfilment)}, in {view.groups.length} steps.
      </p>
      {d.mode === "fallback" ? (
        <p className="chat__note">Prepared plan shown: the language model could not decide ({d.reason}).</p>
      ) : null}
      <button type="button" className="btn btn--primary" onClick={() => showRecoveryPlan(view)} disabled={open}>
        Show recovery plan
      </button>
    </div>
  );
}

function Entry({ entry }: { entry: ChatEntry }) {
  switch (entry.kind) {
    case "user":
      return <p className="chat__user">{entry.text}</p>;
    case "assistant":
      return <p className="chat__bot">{entry.text}</p>;
    case "disruption":
      return <Disruption view={entry.view} />;
    case "recovery":
      return <Recovery view={entry.view} />;
    case "error":
      return <p className="scenario__err mono">{entry.text}</p>;
  }
}

/** Left-hand assistant chat over the Dover corridor graph. */
export function ResiliencePanel() {
  const r = useOps((s) => s.resilience);
  const live = useOps((s) => s.meta?.engine === "turingdb" && s.meta.graph === "dover");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (r.open && live && !r.exercises.length) void loadExercises();
  }, [r.open, live, r.exercises.length]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [r.chat.length, r.progress]);
  if (!r.open || !live) return null;
  const busy = Boolean(r.running);
  const send = () => void askAssistant();
  return (
    <section className="chat glass" aria-label="Assistant">
      <header className="scenario__head">
        <h3>Assistant · Dover corridor</h3>
        <div className="chat__headbtns">
          <button type="button" className="btn btn--quiet" onClick={clearChat} disabled={busy || !r.chat.length}>
            Clear
          </button>
          <button type="button" className="iconbtn" aria-label="Close assistant" onClick={() => setResilienceOpen(false)}>
            ×
          </button>
        </div>
      </header>
      <div className="chat__log" aria-live="polite">
        {!r.chat.length ? (
          <p className="chat__bot">
            Describe a disruption in the London–Dover–Paris corridor. I will trace what breaks through the TuringDB
            dependency graph, then work out and test a recovery plan.
          </p>
        ) : null}
        {r.chat.map((e, i) => (
          <Entry key={i} entry={e} />
        ))}
        {busy ? (
          <p className="chat__status">
            <span className="spinner" aria-hidden />
            {r.progress ? `Recovery agent: ${ACTION_LABELS[r.progress.action] ?? r.progress.action}…` : "Working…"}
          </p>
        ) : null}
        <div ref={end} />
      </div>
      {!busy && r.exercises.length ? (
        <div className="chat__suggestions" role="group" aria-label="Suggestions">
          {r.exercises.map((ex) => (
            <button key={ex.scenario_id} type="button" className="chip chat__chip" disabled={busy}
              onClick={() => void askSuggestion(ex)}>
              {ex.prompt}
            </button>
          ))}
        </div>
      ) : null}
      <form className="chat__input" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea
          aria-label="Message"
          rows={2}
          value={r.question}
          disabled={busy}
          placeholder="Ask about a disruption…"
          onChange={(e) => setChatQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" className="btn btn--primary" disabled={busy || r.question.trim().length < 2}>
          Send
        </button>
      </form>
    </section>
  );
}
