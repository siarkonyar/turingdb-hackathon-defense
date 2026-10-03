import { useEffect } from "react";

import { BottomBar } from "./components/BottomBar";
import { ContextMenu } from "./components/ContextMenu";
import { HoverCard } from "./components/HoverCard";
import { KpiStrip } from "./components/KpiStrip";
import { LayerRail } from "./components/LayerRail";
import { NodeDrawer } from "./components/NodeDrawer";
import { Toasts } from "./components/Toasts";
import { WargamePanel } from "./components/WargamePanel";
import { formatPercent } from "./lib/format";
import { MapView } from "./map/MapView";
import { bootstrap } from "./state/actions";
import { activeBranchInfo, useOps } from "./state/store";

function ContextBar() {
  const meta = useOps((s) => s.meta);
  const branch = useOps(activeBranchInfo);
  const diff = useOps((s) => (s.diffOpen && s.diff?.result ? s.diff.result : null));
  const busy = useOps((s) => s.busy);
  const live = meta?.engine === "turingdb";
  return (
    <div className="contextbar">
      <span className={`engine glass${live ? " engine--live" : ""}`} title={live ? "Serving from TuringDB" : "Serving mock fixtures"}>
        <span className="engine__dot" aria-hidden />
        <span className="mono">{live ? `TURINGDB · ${meta?.graph}` : "MOCK FIXTURES"}</span>
      </span>
      {diff ? (
        <span className="ctxpill glass mono">
          DIFF {diff.a} → {diff.b}
        </span>
      ) : branch && branch.kind !== "main" ? (
        <span className="ctxpill glass">
          <span className="ctxpill__kind">{branch.kind}</span>
          {branch.label}
          {branch.kind === "hypothesis" ? <span className="mono"> · {formatPercent(branch.confidence)}</span> : null}
        </span>
      ) : null}
      {busy ? (
        <span className="ctxpill glass ctxpill--busy">
          <span className="spinner" aria-hidden />
          {busy}
        </span>
      ) : null}
    </div>
  );
}

function Splash() {
  const phase = useOps((s) => s.phase);
  const error = useOps((s) => s.error);
  if (phase === "ready") return null;
  return (
    <div className="splash" role={phase === "error" ? "alert" : "status"}>
      <div className="splash__card glass">
        {phase === "loading" ? (
          <>
            <span className="spinner" aria-hidden />
            <span>Loading the operating picture</span>
          </>
        ) : (
          <>
            <strong>Cannot load the operating picture</strong>
            <span className="splash__err mono">{error}</span>
            <span className="splash__hint">
              Start the API with <code>uv run uvicorn api.main:app</code> and reload.
            </span>
          </>
        )}
      </div>
    </div>
  );
}

export function App() {
  const wargameOpen = useOps((s) => s.wargame.open);
  useEffect(() => {
    void bootstrap();
  }, []);

  return (
    <div className={`app${wargameOpen ? " app--wargame" : ""}`}>
      <MapView />
      <div className="vignette" aria-hidden />
      <LayerRail />
      <KpiStrip />
      <ContextBar />
      <NodeDrawer />
      <WargamePanel />
      <BottomBar />
      <HoverCard />
      <ContextMenu />
      <Toasts />
      <Splash />
    </div>
  );
}
