// Pure helpers for the step-by-step impact cascade: one colour per degree (same on the map, in the ladder
// and in the vulnerability tree), step clamping, the operator-facing labels and the map focus per step.

import type { CascadeHit, CascadeResponse, CascadeStage } from "../api/types";
import type { RGBA } from "../map/colors";

export const MAX_LABELS_PER_DEGREE = 8;
const ORIGIN_ZOOM = 4;
const MIN_ZOOM = 1.5; // MapView minZoom: the whole world just fits a desktop viewport
const MAX_ZOOM = 6;

/** Hot (degree 1, nearest the shock) to cool (far tail). Distinct hues so "which degree" reads at a glance. */
export const DEGREE_COLORS: RGBA[] = [
  [235, 72, 76, 255],
  [244, 114, 54, 255],
  [245, 166, 35, 255],
  [236, 204, 58, 255],
  [163, 207, 72, 255],
  [74, 196, 140, 255],
  [56, 189, 212, 255],
  [61, 139, 240, 255],
  [124, 110, 240, 255],
  [178, 98, 226, 255],
  [214, 92, 184, 255],
  [190, 200, 214, 255],
];
const FALLBACK_COLOR: RGBA = [235, 72, 76, 255]; // degree 1, for the type checker

export function degreeColor(degree: number): RGBA {
  const i = Math.min(DEGREE_COLORS.length - 1, Math.max(0, degree - 1));
  return DEGREE_COLORS[i] ?? FALLBACK_COLOR;
}

export function degreeCss(degree: number): string {
  const [r, g, b] = degreeColor(degree);
  return `rgb(${r} ${g} ${b})`;
}

export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  const suffix = ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

export function clampStep(step: number, result: CascadeResponse): number {
  return Math.min(result.max_degree, Math.max(0, Math.round(step)));
}

export function visibleStages(result: CascadeResponse, step: number): CascadeStage[] {
  return result.stages.slice(0, clampStep(step, result));
}

export function currentStage(result: CascadeResponse, step: number): CascadeStage | null {
  const s = clampStep(step, result);
  return s > 0 ? result.stages[s - 1] ?? null : null;
}

export function topHits(stage: CascadeStage, n = MAX_LABELS_PER_DEGREE): CascadeHit[] {
  return stage.hits.slice(0, n); // the server sorts hits by severity, highest first
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** "closed" for routes (chokepoints, ports), "lost" for everything else, nothing for an exercise event. */
export function lossVerb(result: CascadeResponse): string {
  if (result.origin_kind === "event") return "";
  return result.origin_kind === "chokepoint" || result.origin_kind === "port" ? "closed" : "lost";
}

/** What a hit's severity means, for the step label: supply volume (Plan A) or service availability. */
function lossPhrase(result: CascadeResponse, st: CascadeStage): string {
  const noun = st.count === 1 ? "facility" : "facilities";
  if (result.measure === "service_loss") {
    return `${st.count.toLocaleString("en-GB")} ${noun}, ports or routes lose service (mean ${pct(st.mean_severity)} at the worst point)`;
  }
  return `${st.count.toLocaleString("en-GB")} ${st.count === 1 ? "facility loses" : "facilities lose"} supply (mean ${pct(st.mean_severity)} of inbound volume)`;
}

function originPhrase(result: CascadeResponse): string {
  const verb = lossVerb(result);
  if (verb) return `${result.origin.name} ${verb}`;
  const n = result.origins?.length ?? 0;
  return `${result.origin.name}: ${n.toLocaleString("en-GB")} initial failure${n === 1 ? "" : "s"}`;
}

export function stepLabel(result: CascadeResponse, step: number): string {
  const name = result.origin.name;
  const s = clampStep(step, result);
  if (result.connected === false) return `${name} is not connected to anything in the TuringDB graph dataset.`;
  const head = originPhrase(result);
  if (!result.max_degree) return `${head}. No facility loses at least ${pct(result.min_severity)} of its supply.`;
  if (s === 0) return `${head}. Impact reaches ${result.max_degree} degrees: press Continue for the 1st degree.`;
  const st = result.stages[s - 1];
  if (!st) return `${head}.`;
  const end = s === result.max_degree ? " End of the cascade." : "";
  return `${ordinal(s)} degree of ${result.max_degree}: ${lossPhrase(result, st)}.${end}`;
}

export interface Headline {
  degrees: number;
  hops: number;
  affected: number;
  reached: number;
  reachMs: number | null;
  totalMs: number;
  queries: number;
  depthLimit: number;
}

export function headline(r: CascadeResponse): Headline {
  return {
    degrees: r.max_degree,
    hops: r.graph_hops,
    affected: r.total_affected,
    reached: r.reach.reached,
    reachMs: r.reach.ms ?? null,
    totalMs: r.latency_ms,
    queries: r.queries?.length ?? 0,
    depthLimit: r.reach.depth_limit,
  };
}

export interface Focus {
  lon: number;
  lat: number;
  zoom: number;
}

const FIT_WIDTH_PX = 760; // map area left of MapView's right fly padding (which already clears the panel)
const FIT_HEIGHT_PX = 520;
const FLY_PAD_RIGHT_PX = 420; // MapView DRAWER_PAD: flyTo centres in the area left of it
const TILE_PX = 512;
const MAX_MERCATOR_LAT = 85;

const mercatorY = (lat: number) => {
  const phi = (Math.max(-MAX_MERCATOR_LAT, Math.min(MAX_MERCATOR_LAT, lat)) * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + phi / 2));
};
const mercatorLat = (y: number) => (Math.atan(Math.sinh(y)) * 180) / Math.PI;

/** Centre and zoom that fit the current degree's nodes (plus the origin at degree 1) in Web Mercator. */
export function cascadeFocus(result: CascadeResponse, step: number): Focus {
  const st = currentStage(result, step);
  const nodes = (st?.hits ?? []).map((h) => h.node);
  if (st?.degree === 1) nodes.push(result.origin, ...(result.origins ?? []));
  const pts = nodes.filter((n) => n.lon != null && n.lat != null);
  if (!st || !pts.length) return { lon: result.origin.lon ?? 0, lat: result.origin.lat ?? 0, zoom: ORIGIN_ZOOM };
  const lons = pts.map((n) => n.lon as number);
  const lats = pts.map((n) => n.lat as number);
  const [west, east, south, north] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const lonSpan = Math.max(east - west, 1);
  const ySpan = Math.max(mercatorY(north) - mercatorY(south), 0.02);
  const fit = Math.min(
    Math.log2((FIT_WIDTH_PX * 360) / (TILE_PX * lonSpan)),
    Math.log2((FIT_HEIGHT_PX * 2 * Math.PI) / (TILE_PX * ySpan)),
  );
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, fit));
  // A stage wider than the screen: undo the right fly padding so the whole world is centred on screen
  // (the far east then sits under the translucent panel instead of the far west being cut off).
  const unpad = fit < MIN_ZOOM ? (FLY_PAD_RIGHT_PX / 2) * (360 / (TILE_PX * 2 ** zoom)) : 0;
  return { lon: (west + east) / 2 - unpad, lat: mercatorLat((mercatorY(south) + mercatorY(north)) / 2), zoom };
}
