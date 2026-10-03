import { askCascade, clearCascade, runCascadeFor, setCascadeOpen, setCascadeQuestion } from "../state/cascade";
import { useOps } from "../state/store";
import { CascadeStepper } from "./CascadeStepper";
import { ScenarioPrompt } from "./ScenarioPrompt";

const EXAMPLES = [
  "What happens if the Strait of Hormuz closes?",
  "Taiwan Strait blockade",
  "Port of Busan closes",
  "Red Sea shipping stops",
];

/** "What breaks if X falls?" — one deep TuringDB query, revealed one impact degree at a time. */
export function CascadePanel() {
  const c = useOps((s) => s.cascade);
  if (!c.open) return null;
  const close = () => {
    setCascadeOpen(false);
    if (c.source?.kind === "query") clearCascade();
  };
  return (
    <section className="scenario cascade-panel glass" aria-label="Impact cascade">
      <header className="scenario__head">
        <h3>Impact cascade</h3>
        <button type="button" className="iconbtn" aria-label="Close impact cascade" onClick={close}>
          ×
        </button>
      </header>
      <p className="scenario__hint">
        Ask what happens if a chokepoint, port, facility, company, country, power plant or supply item is lost.
        TuringDB walks the supply network in one deep
        query; the map then reveals who loses supply, one degree at a time. Severity = share of a facility's
        inbound supply volume lost; shown when at least 5%.
      </p>
      <ScenarioPrompt
        label="Impact question"
        value={c.question}
        onChange={setCascadeQuestion}
        onSubmit={() => void askCascade()}
        busy={c.loading}
        submitLabel="Ask"
        busyLabel="Thinking…"
        rows={2}
        placeholder="What happens if the Strait of Hormuz closes?"
      />
      <div className="cascade__examples">
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="chip" onClick={() => setCascadeQuestion(q)}>
            {q}
          </button>
        ))}
      </div>
      {c.error ? <p className="scenario__err mono">{c.error}</p> : null}
      {c.candidates.length ? (
        <div className="cascade__candidates" role="group" aria-label="Choose a place">
          {c.candidates.map((cand) => (
            <button key={cand.node.id} type="button" className="chip" onClick={() => void runCascadeFor(cand.node.id, cand.node.name)}>
              {cand.node.name} <span className="mono">{cand.origin_kind}</span>
            </button>
          ))}
        </div>
      ) : null}
      {c.source?.kind === "query" ? <CascadeStepper /> : null}
    </section>
  );
}
