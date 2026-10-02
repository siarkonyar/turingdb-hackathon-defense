// Cascade arcs: curved paths from the struck node outwards, timed per hop so impact visibly
// propagates through the dependency chain. Rendered with a TripsLayer (time = ms since strike).

import type { Arc } from "../api/types";

export type LonLat = [number, number];

export interface ArcTrip {
  path: LonLat[];
  timestamps: number[];
  hop: number;
  targetId: string;
}

export const ARC_SEGMENTS = 40;
const BEND = 0.18; // control-point offset as a fraction of chord length
const HOP_DELAY_MS = 520;
const MIN_DRAW_MS = 380;
const MAX_DRAW_MS = 1100;
const MS_PER_DEGREE = 70;

/** Quadratic Bézier between two points, bowed to the left of travel (stable for any direction). */
export function curvedPath(source: LonLat, target: LonLat, segments = ARC_SEGMENTS): LonLat[] {
  const [x0, y0] = source;
  const [x1, y1] = target;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const cx = (x0 + x1) / 2 - dy * BEND;
  const cy = (y0 + y1) / 2 + dx * BEND;
  const pts: LonLat[] = [];
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const u = 1 - t;
    pts.push([u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1]);
  }
  return pts;
}

export function drawDuration(source: LonLat, target: LonLat): number {
  const dist = Math.hypot(target[0] - source[0], target[1] - source[1]);
  return Math.min(MAX_DRAW_MS, Math.max(MIN_DRAW_MS, dist * MS_PER_DEGREE));
}

/** Trips for every arc; with reduced motion every arc is complete at t=0. */
export function arcTrips(arcs: readonly Arc[], reducedMotion: boolean): { trips: ArcTrip[]; durationMs: number } {
  let duration = 0;
  const trips = arcs.map((arc) => {
    const path = curvedPath(arc.source, arc.target);
    const start = reducedMotion ? 0 : (arc.hop - 1) * HOP_DELAY_MS;
    const span = reducedMotion ? 0 : drawDuration(arc.source, arc.target);
    duration = Math.max(duration, start + span);
    const timestamps = path.map((_, i) => start + (span * i) / (path.length - 1));
    return { path, timestamps, hop: arc.hop, targetId: arc.target_id };
  });
  return { trips, durationMs: duration };
}

/** When each affected node should light up: the moment its arc finishes drawing. */
export function arrivalTimes(trips: readonly ArcTrip[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const t of trips) out.set(t.targetId, t.timestamps[t.timestamps.length - 1] ?? 0);
  return out;
}
