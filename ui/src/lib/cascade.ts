// Pure helpers for the step-by-step impact cascade: one colour per degree (same on the map, in the ladder
// and in the vulnerability tree), step clamping, the operator-facing labels and the map focus per step.

import type { CascadeHit, CascadeResponse, CascadeStage } from "../api/types";
import type { RGBA } from "../map/colors";

export const MAX_LABELS_PER_DEGREE = 8;
const ORIGIN_ZOOM = 4;
const MIN_ZOOM = 1.8;
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

export function stepLabel(result: CascadeResponse, step: number): string {
  const name = result.origin.name;
  const s = clampStep(step, result);
  if (!result.max_degree) return `${name} closed. No facility loses at least ${pct(result.min_severity)} of its supply.`;
  if (s === 0) return `${name} closed. Impact reaches ${result.max_degree} degrees: press Continue for the 1st degree.`;
  const st = result.stages[s - 1];
  if (!st) return `${name} closed.`;
  const noun = st.count === 1 ? "facility loses" : "facilities lose";
  const end = s === result.max_degree ? " End of the cascade." : "";
  return `${ordinal(s)} degree of ${result.max_degree}: ${st.count.toLocaleString("en-GB")} ${noun} supply (mean ${pct(st.mean_severity)} of inbound volume).${end}`;
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

export function cascadeFocus(result: CascadeResponse, step: number): Focus {
  const st = currentStage(result, step);
  const pts = (st?.hits ?? []).map((h) => h.node).filter((n) => n.lon != null && n.lat != null);
  if (!pts.length) return { lon: result.origin.lon ?? 0, lat: result.origin.lat ?? 0, zoom: ORIGIN_ZOOM };
  const lons = pts.map((n) => n.lon as number);
  const lats = pts.map((n) => n.lat as number);
  const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats), 1);
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.log2(360 / span) - 0.5));
  return { lon: lons.reduce((a, b) => a + b, 0) / lons.length, lat: lats.reduce((a, b) => a + b, 0) / lats.length, zoom };
}
