import { setScenarioOpen } from "../state/actions";
import { setOps, useOps } from "../state/store";
import { setWargameOpen } from "../state/wargame";
import { BranchSwitcher } from "./BranchSwitcher";
import { DiffPanel } from "./DiffPanel";
import { ScenarioAgent } from "./ScenarioAgent";
import { TimeSlider } from "./TimeSlider";

export function BottomBar() {
  const diffOpen = useOps((s) => s.diffOpen);
  const scenarioOpen = useOps((s) => s.scenario.open);
  const wargameOpen = useOps((s) => s.wargame.open);
  const live = useOps((s) => s.meta?.engine === "turingdb");
  return (
    <footer className="bottombar glass">
      <BranchSwitcher />
      <TimeSlider />
      <div className="bottombar__actions">
        {live ? (
          <>
            <button
              type="button"
              className={`btn btn--quiet bottombar__diff${scenarioOpen ? " is-on" : ""}`}
              aria-pressed={scenarioOpen}
              title="Ask a natural-language what-if; the agent simulates it in a TuringDB branch"
              onClick={() => setScenarioOpen(!scenarioOpen)}
            >
              Scenario
            </button>
            <button
              type="button"
              className={`btn btn--quiet bottombar__diff${wargameOpen ? " is-on" : ""}`}
              aria-pressed={wargameOpen}
              title="Turn-based red vs blue on TuringDB branches"
              onClick={() => setWargameOpen(!wargameOpen)}
            >
              Wargame
            </button>
          </>
        ) : null}
        <button
          type="button"
          className={`btn btn--quiet bottombar__diff${diffOpen ? " is-on" : ""}`}
          aria-pressed={diffOpen}
          onClick={() => setOps({ diffOpen: !diffOpen })}
        >
          Diff
        </button>
      </div>
      <DiffPanel />
      <ScenarioAgent />
    </footer>
  );
}
