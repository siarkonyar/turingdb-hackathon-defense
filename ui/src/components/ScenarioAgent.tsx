import { askScenario, setScenarioOpen, setScenarioQuestion } from "../state/actions";
import { useOps } from "../state/store";

/** Natural-language scenario simulation: question -> agent -> TuringDB branch -> map. */
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
        event in its own branch, and the map shows the affected graph.
      </p>
      <textarea
        className="scenario__input"
        rows={3}
        value={sc.question}
        disabled={sc.loading}
        onChange={(e) => setScenarioQuestion(e.target.value)}
        placeholder="A catastrophic event has destroyed everything across Manchester…"
      />
      <div className="scenario__actions">
        <button type="button" className="btn" disabled={sc.loading || !!unavailable} onClick={() => void askScenario()}>
          {sc.loading ? "Simulating…" : "Simulate"}
        </button>
        {sc.status?.model ? <span className="scenario__model mono">{sc.status.model}</span> : null}
      </div>
      {unavailable ? (
        <p className="scenario__err mono">Agent unavailable: {sc.status?.reason}</p>
      ) : null}
      {sc.loading ? (
        <p className="scenario__status">
          <span className="spinner" aria-hidden /> The agent is querying TuringDB and building a branch — this
          can take up to a minute.
        </p>
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
