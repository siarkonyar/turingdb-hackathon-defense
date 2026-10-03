import { useEffect } from "react";

import { currentStage, degreeCss, headline, ordinal, stepLabel, topHits } from "../lib/cascade";
import { formatLatency } from "../lib/format";
import { flyToNode } from "../state/actions";
import { cascadeGoTo, cascadeNext, cascadePrev, cascadeReset, cascadeShowAll } from "../state/cascade";
import { useOps } from "../state/store";

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** Headline (TuringDB speed + depth), degree ladder, step controls, and the current degree's worst hits. */
export function CascadeStepper() {
  const c = useOps((s) => s.cascade);
  const r = c.result;

  useEffect(() => {
    if (!r) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (typing) return;
      if (e.key === "ArrowRight") cascadeNext();
      if (e.key === "ArrowLeft") cascadePrev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [r]);

  if (!r) return null;
  const h = headline(r);
  const cur = currentStage(r, c.step);
  const maxCount = Math.max(1, ...r.stages.map((s) => s.count));
  const atEnd = c.step >= r.max_degree;

  return (
    <div className="cascade" aria-live="polite">
      <div className="cascade__headline">
        <div className="cascade__big">
          <span className="cascade__num">{h.degrees}</span> degrees
          <span className="cascade__sep">·</span>
          <span className="cascade__num">{h.hops}</span> graph hops
          <span className="cascade__sep">·</span>
          <span className="cascade__num">{h.affected.toLocaleString("en-GB")}</span> facilities
        </div>
        <div className="cascade__speed mono">
          TuringDB: {h.depthLimit}-hop query reached {h.reached.toLocaleString("en-GB")} facilities in{" "}
          <strong>{formatLatency(h.reachMs)} ms</strong> · whole answer {formatLatency(h.totalMs)} ms over {h.queries} queries
        </div>
        <details className="cascade__cypher">
          <summary>Show the deep query</summary>
          <code className="mono">{r.reach.cypher}</code>
        </details>
      </div>

      <p className="cascade__step">{stepLabel(r, c.step)}</p>

      <ol className="cascade__ladder" aria-label="Impact degrees">
        <li className={`cascade__rung cascade__rung--origin${c.step === 0 ? " is-current" : ""}`}>
          <button type="button" onClick={() => cascadeGoTo(0)}>
            <span className="cascade__swatch cascade__swatch--origin" aria-hidden />
            <span className="cascade__deg">Origin</span>
            <span className="cascade__count">{r.origin.name}</span>
          </button>
        </li>
        {r.stages.map((st) => {
          const revealed = st.degree <= c.step;
          return (
            <li key={st.degree} className={`cascade__rung${st.degree === c.step ? " is-current" : ""}${revealed ? "" : " is-hidden"}`}>
              <button type="button" onClick={() => cascadeGoTo(st.degree)} aria-label={`Show up to the ${ordinal(st.degree)} degree`}>
                <span className="cascade__swatch" style={{ background: degreeCss(st.degree) }} aria-hidden />
                <span className="cascade__deg">{ordinal(st.degree)} degree</span>
                <span className="cascade__count">{revealed ? `+${st.count.toLocaleString("en-GB")}` : "?"}</span>
                <span className="cascade__bar" aria-hidden>
                  <span style={{ width: revealed ? `${(100 * st.count) / maxCount}%` : 0, background: degreeCss(st.degree) }} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="cascade__controls">
        <button type="button" className="btn btn--quiet" onClick={cascadePrev} disabled={c.step === 0}>
          ← Back
        </button>
        <button type="button" className="btn btn--primary" onClick={cascadeNext} disabled={atEnd}>
          {c.step === 0 ? "Continue: 1st degree →" : atEnd ? "End of cascade" : `Continue: ${ordinal(c.step + 1)} degree →`}
        </button>
        <button type="button" className="btn btn--quiet" onClick={cascadeShowAll} disabled={atEnd}>
          Show all
        </button>
        <button type="button" className="btn btn--quiet" onClick={cascadeReset} disabled={c.step === 0}>
          Reset
        </button>
      </div>

      {cur ? (
        <ul className="cascade__hits" aria-label={`Most affected at the ${ordinal(cur.degree)} degree`}>
          {topHits(cur, 5).map((hit) => (
            <li key={hit.node.id}>
              <button type="button" onClick={() => flyToNode(hit.node, 6)}>
                <span className="cascade__swatch" style={{ background: degreeCss(cur.degree) }} aria-hidden />
                <span className="cascade__hitname">{hit.node.name}</span>
                <span className="mono cascade__sev">{pct(hit.severity)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {atEnd && r.platforms.length ? (
        <div className="cascade__platforms">
          <h4>Weapon platforms exposed</h4>
          <ul>
            {r.platforms.slice(0, 8).map((p) => (
              <li key={p.name}>
                {p.name} <span className="mono">{pct(p.severity)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : atEnd ? (
        <p className="cascade__note">No weapon platform's final assembly loses at least {pct(r.min_severity)} of its supply.</p>
      ) : null}
    </div>
  );
}
