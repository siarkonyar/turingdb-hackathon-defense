// Timeline helpers: the slider works in epoch seconds across reports, drone tracks and commits.

import type { Commit, Report, Track } from "../api/types";

export function isoToEpoch(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

export function epochToIso(epoch: number): string {
  return new Date(epoch * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

const PAD_S = 600;

export function timelineDomain(
  reports: readonly Report[],
  tracks: readonly Track[],
  commits: readonly Commit[],
): [number, number] | null {
  const stamps: number[] = [];
  for (const r of reports) {
    const t = isoToEpoch(r.node.timestamp);
    if (t !== null) stamps.push(t);
  }
  for (const tr of tracks) {
    const first = tr.timestamps[0];
    const last = tr.timestamps[tr.timestamps.length - 1];
    if (first !== undefined && last !== undefined) stamps.push(first, last);
  }
  for (const c of commits) {
    const t = isoToEpoch(c.time);
    if (t !== null) stamps.push(t);
  }
  if (!stamps.length) return null;
  return [Math.min(...stamps) - PAD_S, Math.max(...stamps) + PAD_S];
}

export interface TrackPosition {
  lon: number;
  lat: number;
  headingDeg: number;
}

/** Interpolated position of a track at time t (epoch s); null outside the track's time span. */
export function positionAt(track: Track, t: number): TrackPosition | null {
  const ts = track.timestamps;
  const n = ts.length;
  if (n < 2 || t < (ts[0] as number) || t > (ts[n - 1] as number)) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((ts[mid] as number) <= t) lo = mid;
    else hi = mid;
  }
  const [x0, y0] = track.path[lo] as [number, number];
  const [x1, y1] = track.path[hi] as [number, number];
  const span = (ts[hi] as number) - (ts[lo] as number);
  const f = span > 0 ? (t - (ts[lo] as number)) / span : 0;
  const headingDeg = (Math.atan2(x1 - x0, y1 - y0) * 180) / Math.PI;
  return { lon: x0 + (x1 - x0) * f, lat: y0 + (y1 - y0) * f, headingDeg };
}

/** Like positionAt, but holds the first/last fix outside the track's time span (drones stay on the map). */
export function clampedPositionAt(track: Track, t: number): TrackPosition | null {
  const ts = track.timestamps;
  if (ts.length < 2) return null;
  const first = ts[0] as number;
  const last = ts[ts.length - 1] as number;
  return positionAt(track, Math.min(last, Math.max(first, t)));
}

/** Reports whose timestamp is at or before t. */
export function reportsUntil(reports: readonly Report[], t: number): Report[] {
  return reports.filter((r) => {
    const ts = isoToEpoch(r.node.timestamp);
    return ts !== null && ts <= t;
  });
}

/** Reports that became visible when time moved forward from `prev` to `next`. */
export function newlyArrived(reports: readonly Report[], prev: number, next: number): Report[] {
  if (next <= prev) return [];
  return reports.filter((r) => {
    const ts = isoToEpoch(r.node.timestamp);
    return ts !== null && ts > prev && ts <= next;
  });
}
