// Swappable basemaps, no API keys:
//   carto   - CARTO dark-matter vector style (online, default)
//   pmtiles - a local .pmtiles file rendered with the Protomaps dark flavour (offline / air-gapped)
//   outlines - bundled country outlines, the automatic fallback when either of the above fails
// Both are post-processed by muteStyle() into the same calm navy look with low-opacity labels.

import { addProtocol, type LayerSpecification, type StyleSpecification } from "maplibre-gl";
import type { GeometryCollection, Topology } from "topojson-specification";

export type BasemapKind = "carto" | "pmtiles";

const env = import.meta.env;
export const CARTO_STYLE_URL: string =
  (env.VITE_CARTO_STYLE as string | undefined) ?? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
export const PMTILES_URL: string = (env.VITE_PMTILES_URL as string | undefined) ?? "/basemap/theatre.pmtiles";
const PMTILES_GLYPHS = env.VITE_BASEMAP_GLYPHS as string | undefined; // e.g. /basemap/fonts/{fontstack}/{range}.pbf
export const DEFAULT_BASEMAP: BasemapKind = env.VITE_BASEMAP === "pmtiles" ? "pmtiles" : "carto";

export const PALETTE = {
  background: "#0c131e",
  land: "#0c131e",
  water: "#05080e",
  boundary: "#334055",
  road: "#1a2230",
  label: "#8792a3",
} as const;

const LABEL_OPACITY = 0.5;
const ROAD_OPACITY = 0.45;
const LANDUSE_OPACITY = 0.35;

function idHas(layer: LayerSpecification, ...needles: string[]): boolean {
  return needles.some((n) => layer.id.toLowerCase().includes(n));
}

function muteLayer(layer: LayerSpecification): LayerSpecification {
  switch (layer.type) {
    case "background":
      return { ...layer, paint: { ...layer.paint, "background-color": PALETTE.background } };
    case "fill": {
      if (idHas(layer, "water", "ocean", "sea")) {
        return { ...layer, paint: { ...layer.paint, "fill-color": PALETTE.water, "fill-opacity": 1 } };
      }
      if (idHas(layer, "earth", "land") && !idHas(layer, "landuse", "landcover")) {
        return { ...layer, paint: { ...layer.paint, "fill-color": PALETTE.land } };
      }
      return { ...layer, paint: { ...layer.paint, "fill-opacity": LANDUSE_OPACITY } };
    }
    case "line": {
      if (idHas(layer, "boundar", "admin")) {
        return { ...layer, paint: { ...layer.paint, "line-color": PALETTE.boundary } };
      }
      if (idHas(layer, "water")) return { ...layer, paint: { ...layer.paint, "line-color": PALETTE.water } };
      return { ...layer, paint: { ...layer.paint, "line-opacity": ROAD_OPACITY } };
    }
    case "symbol": {
      if (idHas(layer, "poi", "housenum", "shield", "oneway")) {
        return { ...layer, layout: { ...layer.layout, visibility: "none" } };
      }
      return {
        ...layer,
        paint: {
          ...layer.paint,
          "text-color": PALETTE.label,
          "text-halo-color": PALETTE.background,
          "text-halo-width": 1.2,
          "text-opacity": LABEL_OPACITY,
          "icon-opacity": 0.3,
        },
      };
    }
    default:
      return layer;
  }
}

/** Pure: returns a new style with every layer muted (input untouched). */
export function muteStyle(style: StyleSpecification): StyleSpecification {
  return { ...style, layers: style.layers.map(muteLayer) };
}

async function cartoStyle(): Promise<StyleSpecification> {
  const resp = await fetch(CARTO_STYLE_URL);
  if (!resp.ok) throw new Error(`CARTO style unavailable (${resp.status}); try the offline PMTiles basemap`);
  return muteStyle((await resp.json()) as StyleSpecification);
}

let pmtilesProtocolRegistered = false;

async function pmtilesStyle(): Promise<StyleSpecification> {
  // pmtiles + protomaps styles are only downloaded when the offline basemap is used
  const [{ Protocol }, basemaps] = await Promise.all([import("pmtiles"), import("@protomaps/basemaps")]);
  if (!pmtilesProtocolRegistered) {
    addProtocol("pmtiles", new Protocol().tile);
    pmtilesProtocolRegistered = true;
  }
  const flavor = {
    ...basemaps.namedFlavor("dark"),
    background: PALETTE.background,
    earth: PALETTE.land,
    water: PALETTE.water,
  };
  const url = new URL(PMTILES_URL, window.location.href).href;
  const layers = basemaps
    .layers("protomaps", flavor, { lang: "en" })
    .filter((l) => PMTILES_GLYPHS || l.type !== "symbol"); // no glyphs offline -> no labels
  return muteStyle({
    version: 8,
    ...(PMTILES_GLYPHS ? { glyphs: PMTILES_GLYPHS } : {}),
    sources: {
      protomaps: { type: "vector", url: `pmtiles://${url}`, attribution: "© OpenStreetMap · Protomaps" },
    },
    layers: layers as LayerSpecification[],
  });
}

/** Built-in offline fallback: Natural Earth 1:50m country outlines (public domain, via world-atlas),
 *  served from ui/public so it needs no network and no tiles. Used when the chosen basemap fails. */
export const OUTLINES_URL: string = (env.VITE_OUTLINES_URL as string | undefined) ?? "/basemap/countries-50m.json";

export async function outlineStyle(): Promise<StyleSpecification> {
  const [{ feature, mesh }, resp] = await Promise.all([import("topojson-client"), fetch(OUTLINES_URL)]);
  if (!resp.ok) throw new Error(`country outlines unavailable (${resp.status})`);
  const topo = (await resp.json()) as Topology;
  const countries = topo.objects.countries as GeometryCollection;
  return {
    version: 8,
    sources: {
      land: { type: "geojson", data: feature(topo, countries), attribution: "Natural Earth" },
      borders: { type: "geojson", data: mesh(topo, countries, (a, b) => a !== b) },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": PALETTE.water } },
      { id: "land", type: "fill", source: "land", paint: { "fill-color": PALETTE.land } },
      { id: "coast", type: "line", source: "land", paint: { "line-color": PALETTE.boundary, "line-width": 0.6, "line-opacity": 0.7 } },
      { id: "borders", type: "line", source: "borders", paint: { "line-color": PALETTE.boundary, "line-width": 0.5, "line-opacity": 0.5, "line-dasharray": [2, 2] } },
    ],
  };
}

export function loadBasemap(kind: BasemapKind): Promise<StyleSpecification> {
  return kind === "pmtiles" ? pmtilesStyle() : cartoStyle();
}

/** True when the configured .pmtiles file is actually served (so the offline toggle can work). */
export async function pmtilesAvailable(): Promise<boolean> {
  try {
    const resp = await fetch(PMTILES_URL, { method: "HEAD" });
    const type = resp.headers.get("content-type") ?? "";
    return resp.ok && !type.includes("text/html");
  } catch {
    return false;
  }
}

/** Shown under the map when nothing else loads, so the operating picture never sits on a blank canvas. */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": PALETTE.background } }],
};
