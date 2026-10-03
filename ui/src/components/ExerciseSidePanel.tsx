import { closeSide } from "../state/resilience";
import { useOps } from "../state/store";
import { CascadeStepper } from "./CascadeStepper";
import { RecoveryStepper } from "./RecoveryStepper";

/** Right-hand panel opened from the assistant: the dependency cascade, or the step-by-step recovery plan. */
export function ExerciseSidePanel() {
  const side = useOps((s) => s.resilience.side);
  const disruption = useOps((s) => s.resilience.disruption);
  const recovery = useOps((s) => s.resilience.recovery);
  if (side === "none") return null;
  const title = side === "effects" ? `Effects · ${disruption?.title ?? ""}` : `Recovery plan · ${recovery?.title ?? ""}`;
  return (
    <section className="sidepanel glass" aria-label={title}>
      <header className="scenario__head">
        <h3>{title}</h3>
        <button type="button" className="iconbtn" aria-label="Close panel" onClick={closeSide}>
          ×
        </button>
      </header>
      {side === "effects" ? <CascadeStepper /> : null}
      {side === "recovery" && recovery ? <RecoveryStepper view={recovery} /> : null}
    </section>
  );
}
