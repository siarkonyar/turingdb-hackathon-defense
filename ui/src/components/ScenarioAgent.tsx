import { askScenario, setScenarioOpen, setScenarioQuestion } from "../state/actions";
import { useOps } from "../state/store";
import { ScenarioPrompt } from "./ScenarioPrompt";

/** Natural-language scenario simulation: question -> agent job (live steps) -> TuringDB branch -> map. */
export function ScenarioAgent() {
  const sc = useOps((s) => s.scenario);
  if (!sc.open) return null;

  const unavailable = sc.status && !sc.status.available;

  return (
    <section className="scenario glass" aria-label="Scenario simulation">
      <header className="scenario__head">
        <h3>Scenario simulation</h3>
        <button type="button" className="iconbtn" aria-label="Close scenario" onClick={() => setScenarioOpen(false)}>
          ×
        </button>
      </header>
      <p className="scenario__hint">
        Ask a what-if in plain English. The agent interprets it, runs Cypher against TuringDB, simulates the
        event in its own branch, and the map shows the affected graph. Use the branch as a Wargame base.
      </p>
      <ScenarioPrompt
        label="Scenario question"
        value={sc.question}
        onChange={setScenarioQuestion}
        onSubmit={() => void askScenario()}
        busy={sc.loading}
        disabled={!!unavailable}
        submitLabel="Simulate"
        busyLabel="Simulating…"
        placeholder="Everything in Manchester is destroyed…"
      >
        {sc.status?.model ? <span className="scenario__model mono">{sc.status.model}</span> : null}
      </ScenarioPrompt>
      {unavailable ? <p className="scenario__err mono">Agent unavailable: {sc.status?.reason}</p> : null}
      {sc.loading ? (
        <div className="scenario__status" role="status">
          <span className="spinner" aria-hidden />
          <span>
            {sc.steps.length ? (
              <>
                step {sc.steps.length}: <span className="mono">{sc.steps[sc.steps.length - 1]}</span>
                {sc.thought ? <span className="scenario__thought"> — {sc.thought}</span> : null}
              </>
            ) : (
              "Starting the scenario agent…"
            )}
          </span>
        </div>
      ) : null}
      {sc.error ? <p className="scenario__err mono">{sc.error}</p> : null}
      {sc.explanation ? (
        <div className="scenario__result">
          <p className="scenario__explain">{sc.explanation}</p>
          {sc.impact ? (
            <div className="scenario__impact">
              <span className="dcount dcount--red">
                supply loss {sc.impact.loss_a_pct}% → {sc.impact.loss_b_pct}%
              </span>
              {sc.impact.sites_down_b.length ? (
                <span className="dcount dcount--amber">sites down: {sc.impact.sites_down_b.join(", ")}</span>
              ) : null}
            </div>
          ) : null}
          {sc.deep && (sc.deep.facilities_destroyed || sc.deep.facilities_flagged) ? (
            <div className="scenario__impact">
              <span className="dcount dcount--red">{sc.deep.facilities_destroyed} facilities destroyed</span>
              <span className="dcount dcount--amber">{sc.deep.facilities_flagged} lost a supplier</span>
              <span className="dcount dcount--white">{sc.deep.facilities_downstream.toLocaleString("en-GB")} downstream</span>
              <span className="dcount dcount--white">
                {sc.deep.platforms_built_at_hit_facility.length + sc.deep.platforms_downstream_count} platforms exposed
              </span>
            </div>
          ) : null}
          {sc.branch ? (
            <p className="scenario__branch mono">
              Showing branch #{sc.branch}. Red = destroyed, amber = downstream impact.
            </p>
          ) : null}
          {sc.steps.length ? <p className="scenario__steps mono">tools: {sc.steps.join(" → ")}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
