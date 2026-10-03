import { useShallow } from "zustand/react/shallow";

import { useDoverProfile } from "../hooks/useDoverProfile";
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
  const dover = useDoverProfile();
  const cascadeKpis = useOps(useShallow((s) => {
    const result = s.cascade.result;
    // An exercise cascade is computed for its own disruption branch while the map stays on main.
    if (result && (result.branch === s.activeBranch || s.cascade.source?.kind === "exercise")) {
      const ids = new Set(result.stages.slice(0, s.cascade.step)
        .flatMap((stage) => stage.hits.map((hit) => hit.node.id)));
      if (result.origin.kind === "facility") ids.add(result.origin.id);
      return { affected: ids.size, degree: `${s.cascade.step} / ${result.max_degree}` };
    }
    return {
      affected: [...activeOverlay(s).entries.values()].filter((entry) => entry.node.kind === "facility").length,
      degree: "—",
    };
  }));
  const kpis = useOps(useShallow((s) => kpisFromOverlay(activeOverlay(s))));
  const latency = useOps((s) => s.latency);
  const engine = useOps((s) => s.meta?.engine);
  const engineLabel = engine === "turingdb" ? "TuringDB" : "fixtures";

  return (
    <section className="kpis glass" aria-label="Key indicators">
      {dover ? <>
        <Tile label="Affected facilities" value={formatInt(cascadeKpis.affected)} tone={cascadeKpis.affected ? "amber" : null} />
        <Tile label="Cascade degree" value={cascadeKpis.degree} />
      </> : <>
        <Tile label="Assets at risk" value={formatInt(kpis.assets_at_risk)} tone={kpis.assets_at_risk ? "amber" : null} />
        <Tile
          label="Sites without power"
          value={formatInt(kpis.sites_without_power)}
          tone={kpis.sites_without_power ? "red" : null}
          sub={kpis.suppliers_without_power ? `+${kpis.suppliers_without_power} suppliers` : undefined}
        />
        <Tile label="Parts affected" value={formatInt(kpis.parts_affected)} tone={kpis.parts_affected ? "amber" : null} />
      </>}
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
