// The impact cascade on the map: origin (degree 0) pulses red; revealed degrees stay dimmed; the newest degree
// draws its arcs from each parent and pops its nodes in, in that degree's colour, with degree-number badges.

import type { Layer } from "@deck.gl/core";
import { TripsLayer } from "@deck.gl/geo-layers";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";

import type { CascadeHit, CascadeResponse, CascadeStage, GraphNode } from "../api/types";
import { curvedPath, type LonLat } from "../lib/arcs";
import { currentStage, degreeColor, ordinal, topHits, visibleStages } from "../lib/cascade";
import { RED, WHITE, withAlpha } from "./colors";
import { LABEL_FONT } from "./layers";

export const ARC_DRAW_MS = 900;
const SETTLE_MS = 400;
const PAST_ARC_ALPHA = 0.28;
const PAST_DOT_ALPHA = 0.55;
const OUTLINE: [number, number, number, number] = [7, 11, 18, 255];

const pathCache = new WeakMap<CascadeStage, LonLat[][]>();

export function stagePaths(stage: CascadeStage): LonLat[][] {
  let paths = pathCache.get(stage);
  if (!paths) {
    paths = stage.arcs.map((a) => curvedPath(a.source, a.target));
    pathCache.set(stage, paths);
  }
  return paths;
}

export function cascadeAnimating(c: { result: CascadeResponse | null; step: number; stepStartedAt: number }, now: number): boolean {
  return Boolean(c.result) && now - c.stepStartedAt < ARC_DRAW_MS + SETTLE_MS;
}

export interface CascadeLayerInput {
  result: CascadeResponse;
  step: number;
  elapsedMs: number; // since the step changed
  now: number; // drives the origin pulse
  reducedMotion: boolean;
}

const posOf = (n: GraphNode): [number, number] => [n.lon as number, n.lat as number];
const located = (n: GraphNode) => n.lon != null && n.lat != null;

function label<T>(id: string, data: T[], extra: Record<string, unknown>): Layer {
  return new TextLayer<T>({
    id,
    data,
    fontFamily: LABEL_FONT,
    fontWeight: 700,
    characterSet: "auto",
    sizeUnits: "pixels",
    outlineWidth: 3,
    outlineColor: OUTLINE,
    fontSettings: { sdf: true },
    ...extra,
  });
}

function originLayers(r: CascadeResponse, now: number, reduced: boolean): Layer[] {
  if (!located(r.origin)) return [];
  const pulse = reduced ? 0.5 : (Math.sin(now / 260) + 1) / 2;
  const suffix = r.origin_kind === "facility" ? "LOST" : "CLOSED";
  return [
    new ScatterplotLayer<GraphNode>({
      id: "cascade-origin-ring",
      data: [r.origin],
      getPosition: posOf,
      getRadius: 12 + 10 * pulse,
      radiusUnits: "pixels",
      stroked: true,
      filled: true,
      getFillColor: withAlpha(RED, 0.25),
      getLineColor: withAlpha(RED, 1 - 0.5 * pulse),
      lineWidthMinPixels: 2.5,
      updateTriggers: { getRadius: now, getLineColor: now },
    }),
    label("cascade-origin-label", [r.origin], {
      getPosition: posOf,
      getText: (n: GraphNode) => `${n.name.toUpperCase()} · ${suffix}`,
      getSize: 13,
      getColor: RED,
      getPixelOffset: [0, -28],
    }),
    label("cascade-origin-badge", [r.origin], { getPosition: posOf, getText: () => "0", getSize: 12, getColor: WHITE }),
  ];
}

function pastLayers(stages: CascadeStage[]): Layer[] {
  return stages.flatMap((st) => [
    new PathLayer<LonLat[]>({
      id: `cascade-past-arcs-${st.degree}`,
      data: stagePaths(st),
      getPath: (p) => p,
      getColor: withAlpha(degreeColor(st.degree), PAST_ARC_ALPHA),
      widthMinPixels: 1,
    }),
    new ScatterplotLayer<CascadeHit>({
      id: `cascade-past-dots-${st.degree}`,
      data: st.hits.filter((h) => located(h.node)),
      getPosition: (h) => posOf(h.node),
      getRadius: (h) => 3 + 5 * h.severity,
      radiusUnits: "pixels",
      getFillColor: withAlpha(degreeColor(st.degree), PAST_DOT_ALPHA),
      pickable: true,
    }),
  ]);
}

/** The worst-hit node farthest from the origin: on screen (the focus fits the stage) and clear of the origin
 * label. The text runs from it towards the origin so it is not cut at the map edge. */
function titleAnchor(hits: CascadeHit[], origin: GraphNode): { lon: number; lat: number; anchor: "start" | "end" } {
  const d = (h: CascadeHit) => Math.hypot((h.node.lon as number) - (origin.lon ?? 0), (h.node.lat as number) - (origin.lat ?? 0));
  const far = hits.reduce((best, h) => (d(h) > d(best) ? h : best));
  const lon = far.node.lon as number;
  return { lon, lat: far.node.lat as number, anchor: lon < (origin.lon ?? 0) ? "start" : "end" };
}

function currentLayers(st: CascadeStage, origin: GraphNode, elapsedMs: number, reduced: boolean): Layer[] {
  const color = degreeColor(st.degree);
  const arrived = reduced || elapsedMs >= ARC_DRAW_MS * 0.85;
  const pop = reduced ? 1 : Math.min(1, Math.max(0, (elapsedMs - ARC_DRAW_MS * 0.6) / (ARC_DRAW_MS * 0.5)));
  const hits = st.hits.filter((h) => located(h.node));
  const out: Layer[] = [
    new TripsLayer<LonLat[]>({
      id: `cascade-current-arcs-${st.degree}`,
      data: stagePaths(st),
      getPath: (p) => p,
      getTimestamps: (p) => p.map((_, i) => (ARC_DRAW_MS * i) / Math.max(1, p.length - 1)),
      currentTime: reduced ? Number.MAX_SAFE_INTEGER : elapsedMs,
      trailLength: 1e9,
      fadeTrail: false,
      getColor: withAlpha(color, 0.9),
      widthMinPixels: 2,
      capRounded: true,
      jointRounded: true,
    }),
    new ScatterplotLayer<CascadeHit>({
      id: `cascade-current-dots-${st.degree}`,
      data: hits,
      getPosition: (h) => posOf(h.node),
      getRadius: (h) => (4 + 8 * h.severity) * (0.4 + 0.6 * pop),
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: withAlpha(color, 0.95 * pop),
      getLineColor: withAlpha(WHITE, 0.9 * pop),
      lineWidthMinPixels: 1,
      pickable: true,
      updateTriggers: { getRadius: pop, getFillColor: pop, getLineColor: pop },
    }),
  ];
  if (arrived && hits.length) {
    out.push(
      label(`cascade-badges-${st.degree}`, topHits(st).filter((h) => located(h.node)), {
        getPosition: (h: CascadeHit) => posOf(h.node),
        getText: () => String(st.degree),
        getSize: 12,
        getColor: color,
        getPixelOffset: [0, -14],
      }),
      label(`cascade-stage-title-${st.degree}`, [titleAnchor(topHits({ ...st, hits }), origin)], {
        getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
        getTextAnchor: (d: { anchor: "start" | "end" }) => d.anchor,
        getText: () => `${ordinal(st.degree).toUpperCase()} DEGREE · ${st.count.toLocaleString("en-GB")} ${st.count === 1 ? "FACILITY" : "FACILITIES"}`,
        getSize: 16,
        getColor: color,
        getPixelOffset: [0, -32],
      }),
    );
  }
  return out;
}

export function buildCascadeLayers(i: CascadeLayerInput): Layer[] {
  const cur = currentStage(i.result, i.step);
  const past = visibleStages(i.result, i.step).filter((s) => s !== cur);
  return [
    ...pastLayers(past),
    ...(cur ? currentLayers(cur, i.result.origin, i.elapsedMs, i.reducedMotion) : []),
    ...originLayers(i.result, i.now, i.reducedMotion),
  ];
}
