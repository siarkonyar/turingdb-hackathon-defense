import type { ExerciseTimePoint, RecoveryView } from "../api/types";
import {
  css,
  deltaPp,
  hours,
  LINK_COLORS,
  LINK_LABELS,
  metricRows,
  pct,
  STATE_COLORS,
  STATE_LABELS,
  STATE_ORDER,
  tonnes,
} from "../lib/resilience";

const CHART_W = 360;
const CHART_H = 70;
const MINIMUM = 0.8;

const yOf = (v: number) => CHART_H - 4 - (CHART_H - 8) * v;

function stepPath(pts: ExerciseTimePoint[], window: number): string {
  const x = (h: number) => ((CHART_W * h) / window).toFixed(1);
  return pts
    .map((p, i) => {
      const next = pts[i + 1]?.hour ?? window;
      const y = yOf(p.essential).toFixed(1);
      return `${i ? "L" : "M"}${x(p.hour)},${y} L${x(next)},${y}`;
    })
    .join(" ");
}

/** Essential fulfilment over simulation time (hours), without vs with the plan: a step chart. */
function TimeChart({ before, after, window }: { before: ExerciseTimePoint[]; after: ExerciseTimePoint[]; window: number }) {
  return (
    <figure className="rx__chart">
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label="Essential demand fulfilment over simulation time">
        <line x1={0} x2={CHART_W} y1={yOf(MINIMUM)} y2={yOf(MINIMUM)} className="rx__chart-min" />
        <path d={stepPath(before, window)} className="rx__chart-before" />
        <path d={stepPath(after, window)} className="rx__chart-after" />
      </svg>
      <figcaption>
        <span className="rx__key rx__key--before" /> without recovery <span className="rx__key rx__key--after" /> with the
        plan · dashed = 80% minimum · x: simulation time 0–{window} h (not dependency degree)
      </figcaption>
    </figure>
  );
}

function Plans({ view }: { view: RecoveryView }) {
  return (
    <table className="rx__table">
      <thead>
        <tr><th>#</th><th>Plan</th><th>Essential</th><th>All</th><th>Unmet</th><th>Stock</th><th>Cost</th></tr>
      </thead>
      <tbody>
        {view.candidates.map((p) => (
          <tr key={p.plan_id} className={p.chosen ? "is-chosen" : ""} title={p.summary}>
            <td>{p.rank}</td>
            <td>{p.title}{p.chosen ? " ✓" : ""}</td>
            <td>{pct(p.metrics.essential_fulfilment)}</td>
            <td>{pct(p.metrics.overall_fulfilment)}</td>
            <td>{tonnes(p.metrics.cargo_unmet_t)}</td>
            <td>{tonnes(p.consumption.stock_released_t)}</td>
            <td>{p.metrics.cost_units.toFixed(0)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const signed = (x: number) => `${x >= 0 ? "+" : ""}${x}`;

function Actions({ view }: { view: RecoveryView }) {
  return (
    <>
      <ul className="rx__groups">
        {view.groups.map((g) => (
          <li key={g.key}>
            <div className="rx__group-head">
              <strong>{g.label}</strong>
              <span className="mono">×{g.actions} · ready +{g.ready_h} h</span>
            </div>
            <div className="rx__group-cap">{g.capacity}</div>
            <div className="rx__group-gain mono">
              essential {signed(g.essential_gain)} pp · all {signed(g.overall_gain)} pp · {signed(Math.round(g.cargo_gain_t))} t cargo on time
            </div>
          </li>
        ))}
      </ul>
      <p className="rx__note">Benefit = the plan re-measured without that action group (leave one out).</p>
    </>
  );
}

function Resources({ view }: { view: RecoveryView }) {
  const c = view.consumption;
  return (
    <ul className="rx__facts">
      <li>
        Reserve stock released: {tonnes(c.stock_released_t)} from {c.reserves_drawn} reserves
        {c.reserves_exhausted ? `, ${c.reserves_exhausted} exhausted (first at +${c.first_exhausted_h} h)` : ""}
      </li>
      <li>Mobile generators: {c.generators} · generator fuel {c.generator_fuel_t.toFixed(1)} t</li>
      <li>Aircraft sorties: {c.aircraft_sorties}</li>
      <li>
        Provider spare output: {c.provider_spare_t_day} t/day{c.programme_people ? ` · ${c.programme_people} programme places` : ""}
      </li>
      {Object.entries(c.route_tonnes).map(([route, t]) => (
        <li key={route}>{route.replace(/^Exercise /, "")}: {tonnes(t)} moved</li>
      ))}
    </ul>
  );
}

function Legend({ view }: { view: RecoveryView }) {
  const kinds = (Object.keys(LINK_LABELS) as (keyof typeof LINK_LABELS)[]).filter((k) => view.links.some((l) => l.kind === k));
  return (
    <>
      <ul className="rx__legend">
        {STATE_ORDER.filter((s) => view.counts[s]).map((s) => (
          <li key={s}>
            <span className="rx__swatch" style={{ background: css(STATE_COLORS[s]) }} aria-hidden />
            {STATE_LABELS[s]} <span className="mono">{view.counts[s]}</span>
          </li>
        ))}
      </ul>
      {view.services_relocated || view.programmes_relocated ? (
        <p className="rx__note">
          {view.services_relocated} services and {view.programmes_relocated} programmes relocated to surviving receiving sites.
        </p>
      ) : null}
      <ul className="rx__legend">
        {kinds.map((k) => (
          <li key={k}>
            <span className="rx__line" style={{ background: css(LINK_COLORS[k]) }} aria-hidden />
            {LINK_LABELS[k]} <span className="mono">{view.links.filter((l) => l.kind === k).length}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function ResilienceReport({ view }: { view: RecoveryView }) {
  return (
    <div className="rx">
      <h4 className="rx__h">Plans compared (all figures measured)</h4>
      <Plans view={view} />
      <h4 className="rx__h">Before → after ({view.hours} h window)</h4>
      <table className="rx__table rx__table--ba">
        <tbody>
          {metricRows(view.before, view.after).map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td>{r.before}</td>
              <td className={r.better === null ? "" : r.better ? "is-better" : "is-worse"}>{r.after}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <TimeChart before={view.before_timeline} after={view.after_timeline} window={view.hours} />
      <p className="rx__note">
        Essential demand at or above 80%: {hours(view.before.essential_recovery_h)} without recovery,{" "}
        {hours(view.after.essential_recovery_h)} with the plan ({deltaPp(view.before.essential_fulfilment, view.after.essential_fulfilment)} over the window).
      </p>
      <h4 className="rx__h">Recovery actions: capacity, readiness, measured benefit</h4>
      <Actions view={view} />
      <h4 className="rx__h">Resources consumed</h4>
      <Resources view={view} />
      <h4 className="rx__h">Facilities at the end of the window</h4>
      <Legend view={view} />
      {view.limitations.length ? (
        <>
          <h4 className="rx__h">Residual limitations</h4>
          <ul className="rx__limits">
            {view.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="rx__note">All organisations, capacities and demands are fictional exercise assumptions.</p>
    </div>
  );
}
