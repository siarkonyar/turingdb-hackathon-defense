import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import type { GlyphName } from "../lib/glyphs";
import { pmtilesAvailable } from "../map/basemap";
import { toggleLayer } from "../state/actions";
import { setOps, useOps, type LayerKey } from "../state/store";
import { Glyph } from "./Glyph";

const ITEMS: { key: LayerKey; label: string; glyph: GlyphName }[] = [
  { key: "plant", label: "Plants", glyph: "plant-other" },
  { key: "site", label: "Sites", glyph: "site" },
  { key: "supplier", label: "Suppliers", glyph: "supplier" },
  { key: "facility", label: "Facilities", glyph: "facility" },
  { key: "port", label: "Ports", glyph: "port" },
  { key: "chokepoint", label: "Chokepoints", glyph: "port" },
  { key: "drone", label: "Drones", glyph: "drone" },
  { key: "crime", label: "Crime leads", glyph: "crime" },
  { key: "cyber", label: "Cyber", glyph: "cyber" },
  { key: "report", label: "Reports", glyph: "report" },
];

function Brand() {
  return (
    <div className="brand" title="OpsMap · operational picture over TuringDB">
      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden>
        <path d="M12 2.5L21 7.5V16.5L12 21.5L3 16.5V7.5Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="12" cy="12" r="2.6" fill="currentColor" />
      </svg>
    </div>
  );
}

export function LayerRail() {
  const layers = useOps((s) => s.layers);
  const basemap = useOps((s) => s.basemap);
  const fallback = useOps((s) => s.basemapFallback);
  const counts = useOps(
    useShallow((s) => ({
      plant: s.base.plant.length,
      site: s.base.site.length,
      supplier: s.base.supplier.length,
      facility: s.base.facility.length,
      port: s.base.port.length,
      chokepoint: s.base.chokepoint.length,
      drone: s.base.drone.length,
      crime: s.base.crime.length,
      cyber: s.base.site.length + s.base.supplier.length,
      report: s.reports.length,
    })),
  );
  const [offlineReady, setOfflineReady] = useState(false);
  useEffect(() => {
    void pmtilesAvailable().then(setOfflineReady);
  }, []);

  return (
    <nav className="rail glass" aria-label="Layers">
      <Brand />
      <ul className="rail__list">
        {ITEMS.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className={`rail__item${layers[item.key] ? " is-on" : ""}`}
              aria-pressed={layers[item.key]}
              onClick={() => toggleLayer(item.key)}
              title={`${item.label}: ${counts[item.key].toLocaleString("en-GB")}`}
            >
              <Glyph name={item.glyph} size={18} />
              <span className="rail__label">{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="rail__basemap"
        disabled={!offlineReady && basemap === "carto"}
        onClick={() => setOps({ basemap: basemap === "carto" ? "pmtiles" : "carto" })}
        title={
          offlineReady || basemap === "pmtiles"
            ? "Switch between the online CARTO basemap and the local PMTiles file"
            : "Offline basemap: put a .pmtiles file at ui/public/basemap/theatre.pmtiles"
        }
      >
        <span className="rail__label">{fallback ? "Fallback" : basemap === "carto" ? "Online" : "Offline"}</span>
        <span className="rail__sub mono">{fallback ? "Outlines" : basemap === "carto" ? "CARTO" : "PMTiles"}</span>
      </button>
    </nav>
  );
}
