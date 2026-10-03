import { useEffect } from "react";

import type { ActionGroupView, RecoveryView } from "../api/types";
import { css, groupColor, hours, pct, tonnes } from "../lib/resilience";
import { recoveryNext, recoveryPrev, recoverySteps, setRecoveryStep } from "../state/resilience";
import { useOps } from "../state/store";
import { ResilienceReport } from "./ResilienceReport";

const signed = (x: number) => `${x >= 0 ? "+" : ""}${x}`;
const RESULT_COLOR = "rgb(74 196 140)";

function Group({ g, index }: { g: ActionGroupView; index: number }) {
  return (
    <div className="rstep">
      <p className="cascade__step">
        Step {index} · ready at <strong>+{g.ready_h} h</strong> of simulation time
      </p>
      <h4 className="rstep__title">
        <span className="cascade__swatch" style={{ background: css(groupColor(g.key)) }} aria-hidden /> {g.label}
        <span className="mono"> ×{g.actions}</span>
      </h4>
      <dl className="rstep__facts">
        <dt>Capacity</dt>
        <dd>{g.capacity}</dd>
        <dt>Measured benefit</dt>
        <dd className="mono">
          essential {signed(g.essential_gain)} pp · all demand {signed(g.overall_gain)} pp ·{" "}
          {signed(Math.round(g.cargo_gain_t))} t cargo on time
        </dd>
      </dl>
      <p className="cascade__note">Benefit = the full plan re-measured without this step (leave one out).</p>
    </div>
  );
}

function Start({ view }: { view: RecoveryView }) {
  const d = view.decision;
  return (
    <div className="rstep">
      <p className="cascade__step">
        Starting point: the disruption with no recovery. Essential demand {pct(view.before.essential_fulfilment)}, cargo
        unmet {tonnes(view.before.cargo_unmet_t)}. Press Continue for the first recovery step.
      </p>
      <div className={`rx__decision rx__decision--${d.mode}`}>
        <span className="rx__badge mono">{d.mode === "agent" ? `AGENT · ${d.model ?? "model"}` : "FALLBACK"}</span>
        <p className="rx__rationale">{d.rationale}</p>
        {d.mode === "fallback" ? <p className="rx__note">Prepared plan shown: {d.reason}.</p> : null}
      </div>
    </div>
  );
}

function useArrowKeys(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (typing) return;
      if (e.key === "ArrowRight") recoveryNext();
      if (e.key === "ArrowLeft") recoveryPrev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** The chosen recovery plan revealed one action group at a time, ending with the measured result. */
export function RecoveryStepper({ view }: { view: RecoveryView }) {
  const step = useOps((s) => s.resilience.recoveryStep);
  const last = recoverySteps(view);
  useArrowKeys();
  const next = step < view.groups.length ? view.groups[step]?.label : step === view.groups.length ? "Result" : null;
  const current = step > 0 && step <= view.groups.length ? view.groups[step - 1] : undefined;
  return (
    <div className="cascade" aria-live="polite">
      <div className="cascade__headline cascade__headline--recovery">
        <div className="cascade__big">
          <span className="cascade__num">{view.groups.length}</span> recovery steps
          <span className="cascade__sep">·</span>
          essential <span className="cascade__num">{pct(view.after.essential_fulfilment)}</span>
        </div>
        <div className="cascade__speed mono">
          {view.decision.mode === "agent" ? "Chosen by the recovery agent" : "Prepared plan"} · recovery branch #
          {view.branch.branch} replays disruption #{view.disruption_branch}
          {view.branch.verified ? " · re-measured ✓" : ""}
        </div>
      </div>
      <ol className="cascade__ladder cascade__ladder--recovery" aria-label="Recovery steps">
        <li className={`cascade__rung cascade__rung--origin${step === 0 ? " is-current" : ""}`}>
          <button type="button" onClick={() => setRecoveryStep(0)}>
            <span className="cascade__swatch cascade__swatch--origin" aria-hidden />
            <span className="cascade__deg">Start</span>
            <span className="cascade__count">no recovery</span>
          </button>
        </li>
        {view.groups.map((g, i) => (
          <li key={g.key} className={`cascade__rung${step === i + 1 ? " is-current" : ""}${step > i ? "" : " is-hidden"}`}>
            <button type="button" onClick={() => setRecoveryStep(i + 1)}>
              <span className="cascade__swatch" style={{ background: css(groupColor(g.key)) }} aria-hidden />
              <span className="cascade__deg">Step {i + 1}</span>
              <span className="cascade__count">{step > i ? `${g.label} · ${hours(g.ready_h)}` : "?"}</span>
            </button>
          </li>
        ))}
        <li className={`cascade__rung${step === last ? " is-current" : ""}${step >= last ? "" : " is-hidden"}`}>
          <button type="button" onClick={() => setRecoveryStep(last)}>
            <span className="cascade__swatch" style={{ background: RESULT_COLOR }} aria-hidden />
            <span className="cascade__deg">Result</span>
            <span className="cascade__count">{step >= last ? `essential ${pct(view.after.essential_fulfilment)}` : "?"}</span>
          </button>
        </li>
      </ol>
      <div className="cascade__controls">
        <button type="button" className="btn btn--quiet" onClick={recoveryPrev} disabled={step === 0}>
          ← Back
        </button>
        <button type="button" className="btn btn--primary" onClick={recoveryNext} disabled={!next}>
          {next ? `Continue: ${next} →` : "End of the plan"}
        </button>
        <button type="button" className="btn btn--quiet" onClick={() => setRecoveryStep(last)} disabled={step >= last}>
          Show all
        </button>
        <button type="button" className="btn btn--quiet" onClick={() => setRecoveryStep(0)} disabled={step === 0}>
          Reset
        </button>
      </div>
      {step === 0 ? <Start view={view} /> : null}
      {current ? <Group g={current} index={step} /> : null}
      {step >= last ? <ResilienceReport view={view} /> : null}
    </div>
  );
}
