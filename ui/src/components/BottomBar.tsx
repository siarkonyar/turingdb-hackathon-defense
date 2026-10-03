import { setScenarioOpen } from "../state/actions";
import { setCascadeOpen } from "../state/cascade";
import { setResilienceOpen } from "../state/resilience";
import { setOps, useOps } from "../state/store";
import { setWargameOpen } from "../state/wargame";
import { BranchSwitcher } from "./BranchSwitcher";
import { CascadePanel } from "./CascadePanel";
import { DiffPanel } from "./DiffPanel";
import { ScenarioAgent } from "./ScenarioAgent";
import { useDoverProfile } from "../hooks/useDoverProfile";

export function BottomBar() {
  const dover = useDoverProfile();
  const diffOpen = useOps((s) => s.diffOpen);
  const scenarioOpen = useOps((s) => s.scenario.open);
  const wargameOpen = useOps((s) => s.wargame.open);
  const cascadeOpen = useOps((s) => s.cascade.open);
  const live = useOps((s) => s.meta?.engine === "turingdb");
  const agents = useOps((s) => s.meta?.engine === "turingdb" && s.meta.graph !== "dover");
  const exercisesOpen = useOps((s) => s.resilience.open);
  return (
    <footer className={`bottombar glass${dover ? " bottombar--compact" : ""}`}>
      <BranchSwitcher />
      <div className="bottombar__actions">
        {live ? (
          <>
            <button
              type="button"
              className={`btn btn--quiet bottombar__diff${cascadeOpen ? " is-on" : ""}`}
              aria-pressed={cascadeOpen}
              title="What breaks if a port, chokepoint, facility, company, country, plant or supply item is lost? Step through the impact degree by degree"
              onClick={() => setCascadeOpen(!cascadeOpen)}
            >
              Impact
            </button>
            {dover ? (
              <button
                type="button"
                className={`btn btn--quiet bottombar__diff${exercisesOpen ? " is-on" : ""}`}
                aria-pressed={exercisesOpen}
                title="Ask the assistant about a disruption: what breaks, and how to recover"
                onClick={() => setResilienceOpen(!exercisesOpen)}
              >
                Assistant
              </button>
            ) : null}
            {agents ? (
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
      <CascadePanel />
    </footer>
  );
}
