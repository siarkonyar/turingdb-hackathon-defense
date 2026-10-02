import { setScenarioOpen } from "../state/actions";
import { setOps, useOps } from "../state/store";
import { BranchSwitcher } from "./BranchSwitcher";
import { DiffPanel } from "./DiffPanel";
import { ScenarioAgent } from "./ScenarioAgent";
import { TimeSlider } from "./TimeSlider";

export function BottomBar() {
  const diffOpen = useOps((s) => s.diffOpen);
  const scenarioOpen = useOps((s) => s.scenario.open);
  const live = useOps((s) => s.meta?.engine === "turingdb");
  return (
    <footer className="bottombar glass">
      <BranchSwitcher />
      <TimeSlider />
      {live ? (
        <button
          type="button"
          className={`btn btn--quiet bottombar__diff${scenarioOpen ? " is-on" : ""}`}
          aria-pressed={scenarioOpen}
          title="Ask a natural-language what-if; the agent simulates it in a TuringDB branch"
          onClick={() => setScenarioOpen(!scenarioOpen)}
        >
          Scenario
        </button>
      ) : null}
      <button
        type="button"
        className={`btn btn--quiet bottombar__diff${diffOpen ? " is-on" : ""}`}
        aria-pressed={diffOpen}
        onClick={() => setOps({ diffOpen: !diffOpen })}
      >
        Diff
      </button>
      <DiffPanel />
      <ScenarioAgent />
    </footer>
  );
}
