import { useShallow } from "zustand/react/shallow";

import { formatInt, formatLatency } from "../lib/format";
import { kpisFromOverlay } from "../lib/overlay";
import { activeOverlay, useOps } from "../state/store";

interface TileProps {
  label: string;
  value: string;
  tone?: "amber" | "red" | null;
  sub?: string;
}

function Tile({ label, value, tone, sub }: TileProps) {
  return (
    <div className={`kpi${tone ? ` kpi--${tone}` : ""}`}>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value mono">{value}</div>
      {sub ? <div className="kpi__sub">{sub}</div> : null}
    </div>
  );
}

export function KpiStrip() {
  const kpis = useOps(useShallow((s) => kpisFromOverlay(activeOverlay(s))));
  const latency = useOps((s) => s.latency);
  const engine = useOps((s) => s.meta?.engine);
  const engineLabel = engine === "turingdb" ? "TuringDB" : "fixtures";

  return (
    <section className="kpis glass" aria-label="Key indicators">
      <Tile label="Assets at risk" value={formatInt(kpis.assets_at_risk)} tone={kpis.assets_at_risk ? "amber" : null} />
      <Tile
        label="Sites without power"
        value={formatInt(kpis.sites_without_power)}
        tone={kpis.sites_without_power ? "red" : null}
        sub={kpis.suppliers_without_power ? `+${kpis.suppliers_without_power} suppliers` : undefined}
      />
      <Tile label="Parts affected" value={formatInt(kpis.parts_affected)} tone={kpis.parts_affected ? "amber" : null} />
      <div className="kpi kpi--latency" title={latency ? `round trip ${latency.roundtripMs.toFixed(1)} ms` : undefined}>
        <div className="kpi__label">
          <span className="live-dot" aria-hidden /> Query latency
        </div>
        <div className="kpi__value mono">
          {formatLatency(latency?.ms)}
          <span className="kpi__unit">ms</span>
        </div>
        <div className="kpi__sub mono">
          {latency ? `${latency.op} · ${engineLabel}${latency.queries ? ` · ${latency.queries}q` : ""}` : engineLabel}
        </div>
      </div>
    </section>
  );
}
