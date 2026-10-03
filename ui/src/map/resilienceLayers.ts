// The Dover recovery plan on the map, step by step (like the dependency cascade). Step 0 shows only the lost
// sites; step k adds the links of recovery group k (drawn in over RECOVERY_DRAW_MS, earlier groups dimmed); the
// final "Result" step shows every facility's end state: lost, relocated, restored, partly restored, residual.

import type { Layer } from "@deck.gl/core";
import { TripsLayer } from "@deck.gl/geo-layers";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";

import type { RecoveryLink, RecoveryView, StatePoint } from "../api/types";
import { curvedPath, type LonLat } from "../lib/arcs";
import { LINK_COLORS, STATE_COLORS } from "../lib/resilience";
import { WHITE, withAlpha } from "./colors";
import { LABEL_FONT } from "./layers";

export const RECOVERY_DRAW_MS = 1100;
const SETTLE_MS = 200;
const PAST_ALPHA = 0.3;
const OUTLINE: [number, number, number, number] = [7, 11, 18, 255];
const WIDTH: Record<RecoveryLink["kind"], number> = { route: 5, export: 2.5, relocation: 2.5, power: 1.5, stock: 1.5 };
const POINT_ORDER = ["residual", "improved", "restored", "relocated", "lost"]; // drawn last = on top
const PRIORITY = { route: 1000, export: 500 } as const;
const CLEAR_LON = 0.6; // a label needs this much clear space (degrees) around it at corridor zoom
const CLEAR_LAT = 0.12;

const pathCache = new WeakMap<RecoveryLink, LonLat[]>();
function pathOf(l: RecoveryLink): LonLat[] {
  let p = pathCache.get(l);
  if (!p) {
    p = curvedPath(l.source, l.target);
    pathCache.set(l, p);
  }
  return p;
}

export function recoveryAnimating(stepStartedAt: number, now: number): boolean {
  return now - stepStartedAt < RECOVERY_DRAW_MS + SETTLE_MS;
}

export interface RecoveryLayerInput {
  view: RecoveryView;
  step: number; // 0 = start, 1..groups = recovery steps, groups + 1 = result
  elapsedMs: number;
  reducedMotion: boolean;
}

const pos = (p: StatePoint): [number, number] => [p.node.lon as number, p.node.lat as number];

function radius(p: StatePoint): number {
  if (p.state === "lost" || p.state === "relocated") return 5;
  if (p.state === "restored") return 4.5;
  return 2.5 + 4 * (1 - p.after); // residual / partly restored: bigger = more service still missing
}

/** Before the result only the lost sites show (relocated ones turn blue once their step is revealed). */
function visiblePoints(view: RecoveryView, step: number, revealed: Set<string>): StatePoint[] {
  if (step > view.groups.length) return view.points;
  return view.points
    .filter((p) => p.state === "lost" || p.state === "relocated")
    .map((p) => (p.state === "relocated" && !revealed.has("relocate") ? { ...p, state: "lost" as const } : p));
}

function pointLayer(points: StatePoint[]): Layer {
  const data = [...points].sort((a, b) => POINT_ORDER.indexOf(a.state) - POINT_ORDER.indexOf(b.state));
  return new ScatterplotLayer<StatePoint>({
    id: "recovery-points",
    data,
    getPosition: pos,
    getRadius: radius,
    radiusUnits: "pixels",
    stroked: true,
    filled: true,
    getFillColor: (p) => withAlpha(STATE_COLORS[p.state], p.state === "relocated" ? 0.25 : 0.9),
    getLineColor: (p) => (p.state === "relocated" ? STATE_COLORS.relocated : withAlpha(OUTLINE, 0.9)),
    getLineWidth: (p) => (p.state === "relocated" ? 2 : 1),
    lineWidthUnits: "pixels",
    pickable: true,
    updateTriggers: { getFillColor: data.length, getLineColor: data.length },
  });
}

function pastLinks(links: RecoveryLink[]): Layer {
  return new PathLayer<RecoveryLink>({
    id: "recovery-links-past",
    data: links,
    getPath: pathOf,
    getColor: (l) => withAlpha(LINK_COLORS[l.kind], PAST_ALPHA),
    getWidth: (l) => WIDTH[l.kind],
    widthUnits: "pixels",
  });
}

function currentLinks(links: RecoveryLink[], elapsed: number, reduced: boolean): Layer {
  return new TripsLayer<RecoveryLink>({
    id: "recovery-links-current",
    data: links,
    getPath: pathOf,
    getTimestamps: (l) => pathOf(l).map((_, i, a) => (RECOVERY_DRAW_MS * i) / Math.max(1, a.length - 1)),
    currentTime: reduced ? Number.MAX_SAFE_INTEGER : elapsed,
    trailLength: 1e9,
    fadeTrail: false,
    getColor: (l) => withAlpha(LINK_COLORS[l.kind], 0.95),
    getWidth: (l) => WIDTH[l.kind],
    widthUnits: "pixels",
    capRounded: true,
    jointRounded: true,
  });
}

interface Label {
  position: LonLat;
  text: string;
  kind: RecoveryLink["kind"];
  offset: number; // stacking row for routes that share a midpoint
  priority: number; // when two labels would overlap, the higher priority one is kept
}

/** "Tunnel: ≤200 t/day, 600 t moved, ready +8 h" from "Exercise tunnel corridor: ..." */
function shortLabel(l: RecoveryLink): string {
  const text = l.label.replace(/^Exercise /, "").replace(/ corridor:/, ":");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** One label per route and export; relocations and allocations are summed per receiving site. */
export function recoveryLabels(links: RecoveryLink[]): Label[] {
  const out: Label[] = [];
  let row = 0;
  const byReceiver = new Map<string, RecoveryLink[]>();
  for (const l of links) {
    if (l.kind === "route" || l.kind === "export") {
      const p = pathOf(l);
      const at = p[Math.floor((p.length - 1) * (l.kind === "route" ? 0.5 : 0.85))] ?? l.target;
      out.push({ position: at, text: shortLabel(l), kind: l.kind, offset: l.kind === "route" ? row++ : 0,
        priority: PRIORITY[l.kind] });
    } else {
      byReceiver.set(`${l.kind}|${l.target_id}`, [...(byReceiver.get(`${l.kind}|${l.target_id}`) ?? []), l]);
    }
  }
  for (const group of byReceiver.values()) {
    const first = group[0]!;
    const ready = first.label.match(/ready \+[\d.]+ h/)?.[0] ?? "";
    const what = first.kind === "relocation" ? `${group.length} relocated here` : shortLabel(first);
    out.push({ position: first.target, text: `${what}${ready && first.kind === "relocation" ? `, ${ready}` : ""}`,
      kind: first.kind, offset: 0, priority: group.length });
  }
  return out;
}

/** Keep the most important labels; drop any that would sit on top of one already kept. */
export function declutter(labels: Label[]): Label[] {
  const kept: Label[] = [];
  for (const l of [...labels].sort((a, b) => b.priority - a.priority)) {
    const clash = kept.some((k) => k.offset === l.offset
      && Math.abs(k.position[0] - l.position[0]) < CLEAR_LON && Math.abs(k.position[1] - l.position[1]) < CLEAR_LAT);
    if (!clash) kept.push(l);
  }
  return kept;
}

function labelLayer(links: RecoveryLink[]): Layer {
  return new TextLayer<Label>({
    id: "recovery-link-labels",
    data: declutter(recoveryLabels(links)),
    fontFamily: LABEL_FONT,
    fontWeight: 700,
    characterSet: "auto",
    sizeUnits: "pixels",
    getPosition: (d) => d.position,
    getText: (d) => d.text,
    getSize: (d) => (d.kind === "route" ? 13 : 10.5),
    getColor: (d) => (d.kind === "route" ? WHITE : LINK_COLORS[d.kind]),
    getPixelOffset: (d) => [0, -12 - 15 * d.offset],
    outlineWidth: 3,
    outlineColor: OUTLINE,
    fontSettings: { sdf: true },
  });
}

export function buildRecoveryLayers(i: RecoveryLayerInput): Layer[] {
  const keys = i.view.groups.map((g) => g.key);
  const shown = new Set(keys.slice(0, Math.min(i.step, keys.length)));
  const current = i.step >= 1 && i.step <= keys.length ? keys[i.step - 1] : null;
  const past = i.view.links.filter((l) => shown.has(l.group) && l.group !== current);
  const now = i.view.links.filter((l) => l.group === current);
  const drawn = i.reducedMotion || i.elapsedMs >= RECOVERY_DRAW_MS * 0.8;
  const atResult = i.step > keys.length;
  const summary = i.view.links.filter((l) => l.kind === "route" || l.kind === "export" || l.kind === "relocation");
  const labelled = atResult ? summary : drawn ? now : [];
  return [
    pointLayer(visiblePoints(i.view, i.step, shown)),
    pastLinks(atResult ? i.view.links : past),
    ...(now.length ? [currentLinks(now, i.elapsedMs, i.reducedMotion)] : []),
    ...(labelled.length ? [labelLayer(labelled)] : []),
  ];
}
