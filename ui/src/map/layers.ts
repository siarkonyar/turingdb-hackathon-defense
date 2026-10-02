// deck.gl layer builders. Static layers depend on data/overlay/zoom and are memoised by MapView;
// animated layers (drones, strike arcs, pulses) are rebuilt per animation frame.

import { DataFilterExtension, type DataFilterExtensionProps } from "@deck.gl/extensions";
import { TripsLayer } from "@deck.gl/geo-layers";
import { IconLayer, LineLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer, PickingInfo } from "@deck.gl/core";

import type { GraphNode, Report, Status, Track } from "../api/types";
import type { ArcTrip } from "../lib/arcs";
import { glyphForNode, type GlyphName } from "../lib/glyphs";
import type { DiffClass, Overlay } from "../lib/overlay";
import { clampedPositionAt } from "../lib/time";
import { ALWAYS_VISIBLE, FULL_DETAIL_ZOOM, filterValue, glyphSize, minCapacityForZoom } from "../lib/zoom";
import type { LayerKey, Pulse } from "../state/store";
import { AMBER, ARC, CYBER_RING, RED, TRAIL, WHITE, nodeColor, statusColor, withAlpha, type RGBA } from "./colors";
import type { IconAtlas } from "./iconAtlas";

type Pos = [number, number];
const pos = (n: { lon?: number | null; lat?: number | null }): Pos => [n.lon as number, n.lat as number];
const located = (n: GraphNode) => n.lat != null && n.lon != null;

const LABEL_FONT = "Inter Variable, Inter, system-ui, sans-serif";
const SITE_LABEL_MIN_ZOOM = 3.5;
const DRONE_TRAIL_S = 900;
const SHOCKWAVE_MS = 1300;
const PULSE_MAX_PX = 46;
const IMPACT_POP_MS = 500;
/** Report pins sit up-right of their point so they never cover the asset they mention. */
export const REPORT_OFFSET: [number, number] = [13, -13];

export interface StaticInput {
  plants: GraphNode[];
  facilities: GraphNode[]; // sites + suppliers
  sites: GraphNode[];
  crimes: GraphNode[];
  reports: Report[]; // already cut at the slider time
  overlay: Overlay; // settled overlay (excludes a strike that is still animating)
  overlayKey: string;
  layers: Record<LayerKey, boolean>;
  zoom: number;
  atlas: IconAtlas;
  selectedId: string | null;
  diff: Map<string, { cls: DiffClass; node: GraphNode }> | null;
  nodeIndex: ReadonlyMap<string, GraphNode>;
}

function statusOf(overlay: Overlay, id: string): Status | undefined {
  return overlay.entries.get(id)?.status;
}

function iconFor(node: GraphNode, status: Status | undefined): GlyphName {
  return status === "lost" ? "lost" : glyphForNode(node);
}

export function buildStaticLayers(input: StaticInput): Layer[] {
  const { overlay, overlayKey, layers, atlas, zoom, selectedId, diff } = input;
  const focus = overlay.entries.size > 0 || diff !== null;
  const dimmed = (n: GraphNode) => (diff ? !diff.has(n.id) : focus && !statusOf(overlay, n.id));
  const color = (n: GraphNode) => nodeColor(n, statusOf(overlay, n.id), dimmed(n));
  const triggers = [overlayKey, diff ? diff.size : -1];
  const out: Layer[] = [];

  if (layers.cyber) {
    const exposed = input.facilities.filter((n) => (n.exposure ?? 0) > 0);
    const max = Math.max(1, ...exposed.map((n) => n.exposure ?? 0));
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "cyber-exposure",
        data: exposed,
        getPosition: pos,
        getRadius: (n) => 16 + 26 * ((n.exposure ?? 0) / max),
        radiusUnits: "pixels",
        stroked: true,
        filled: true,
        getFillColor: withAlpha(CYBER_RING, 0.05),
        getLineColor: CYBER_RING,
        lineWidthMinPixels: 1,
      }),
    );
  }

  if (layers.crime && zoom >= 7) {
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "crime",
        data: input.crimes,
        getPosition: pos,
        getRadius: 2.5,
        radiusUnits: "pixels",
        getFillColor: (n) => nodeColor(n, undefined, focus),
        pickable: true,
        updateTriggers: { getFillColor: triggers },
      }),
    );
  }

  if (layers.plant) {
    out.push(
      new IconLayer<GraphNode, DataFilterExtensionProps<GraphNode>>({
        id: "plants",
        data: input.plants,
        iconAtlas: atlas.url,
        iconMapping: atlas.mapping,
        getIcon: (n) => iconFor(n, statusOf(overlay, n.id)),
        getPosition: pos,
        getSize: (n) => glyphSize(n.importance, 8, 20),
        sizeUnits: "pixels",
        sizeScale: zoom >= FULL_DETAIL_ZOOM ? 1.25 : 1,
        getColor: color,
        pickable: true,
        extensions: [new DataFilterExtension({ filterSize: 1 })],
        getFilterValue: (n: GraphNode) =>
          filterValue(n.capacity_mw, Boolean(statusOf(overlay, n.id)) || n.id === selectedId || Boolean(diff?.has(n.id))),
        filterRange: [minCapacityForZoom(zoom), ALWAYS_VISIBLE * 2],
        updateTriggers: { getColor: triggers, getIcon: triggers, getFilterValue: [...triggers, selectedId] },
      }),
    );
  }

  const statused = [...overlay.entries.values()].map((e) => e.node).filter(located);
  if (statused.length) {
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "status-halo",
        data: statused,
        getPosition: pos,
        getRadius: (n) => glyphSize(n.importance, 12, 26),
        radiusUnits: "pixels",
        stroked: true,
        getFillColor: (n) => withAlpha(statusColor(statusOf(overlay, n.id)) ?? AMBER, 0.14),
        getLineColor: (n) => withAlpha(statusColor(statusOf(overlay, n.id)) ?? AMBER, 0.55),
        lineWidthMinPixels: 1,
        updateTriggers: { getFillColor: triggers, getLineColor: triggers },
      }),
    );
  }

  const facilities = input.facilities.filter((n) => (n.kind === "site" ? layers.site : layers.supplier));
  out.push(
    new IconLayer<GraphNode>({
      id: "facilities",
      data: facilities,
      iconAtlas: atlas.url,
      iconMapping: atlas.mapping,
      getIcon: (n) => iconFor(n, statusOf(overlay, n.id)),
      getPosition: pos,
      getSize: (n) => glyphSize(n.importance, 16, 28),
      sizeUnits: "pixels",
      getColor: color,
      pickable: true,
      updateTriggers: { getColor: triggers, getIcon: triggers },
    }),
  );

  if (layers.site && zoom >= SITE_LABEL_MIN_ZOOM) {
    out.push(
      new TextLayer<GraphNode>({
        id: "site-labels",
        data: input.sites,
        getPosition: pos,
        getText: (n) => n.name.replace(/^Site:\s*/, ""),
        getSize: 12,
        sizeUnits: "pixels",
        getColor: (n) => withAlpha(statusColor(statusOf(overlay, n.id)) ?? WHITE, 0.82),
        getPixelOffset: [0, 20],
        fontFamily: LABEL_FONT,
        fontWeight: 600,
        characterSet: "auto",
        outlineWidth: 3,
        outlineColor: [7, 11, 18, 255],
        fontSettings: { sdf: true },
        updateTriggers: { getColor: triggers },
      }),
    );
  }

  if (layers.report) {
    out.push(
      new IconLayer<Report>({
        id: "reports",
        data: input.reports.filter((r) => located(r.node)),
        iconAtlas: atlas.url,
        iconMapping: atlas.mapping,
        getIcon: () => "report",
        getPosition: (r) => pos(r.node),
        getPixelOffset: REPORT_OFFSET,
        getSize: (r) => 12 + 8 * (r.node.confidence ?? 0.5),
        sizeUnits: "pixels",
        getColor: (r) => (diff && !diff.has(r.node.id) ? withAlpha(WHITE, 0.3) : withAlpha(WHITE, 0.9)),
        pickable: true,
        updateTriggers: { getColor: triggers },
      }),
    );
    const selectedReport = input.reports.find((r) => r.node.id === selectedId);
    if (selectedReport && located(selectedReport.node)) {
      const targets = selectedReport.mentions.map((id) => input.nodeIndex.get(id)).filter((n): n is GraphNode => !!n && located(n));
      out.push(
        new LineLayer<GraphNode>({
          id: "report-mentions",
          data: targets,
          getSourcePosition: () => pos(selectedReport.node),
          getTargetPosition: pos,
          getColor: withAlpha(AMBER, 0.7),
          getWidth: 1.5,
          widthUnits: "pixels",
        }),
      );
    }
  }

  if (diff) out.push(...diffLayers(diff, atlas));

  const selected = selectedId ? input.nodeIndex.get(selectedId) : undefined;
  if (selected && located(selected)) {
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "selection",
        data: [selected],
        getPosition: pos,
        getRadius: glyphSize(selected.importance, 15, 28),
        radiusUnits: "pixels",
        stroked: true,
        filled: false,
        getLineColor: AMBER,
        lineWidthMinPixels: 1.5,
      }),
    );
  }
  return out;
}

const DIFF_COLOR: Record<DiffClass, RGBA> = { added: WHITE, removed: RED, changed: AMBER };

function diffLayers(diff: Map<string, { cls: DiffClass; node: GraphNode }>, atlas: IconAtlas): Layer[] {
  const items = [...diff.values()].filter((d) => located(d.node));
  return [
    new ScatterplotLayer<{ cls: DiffClass; node: GraphNode }>({
      id: "diff-rings",
      data: items,
      getPosition: (d) => pos(d.node),
      getRadius: (d) => glyphSize(d.node.importance, 12, 24),
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: (d) => withAlpha(DIFF_COLOR[d.cls], 0.12),
      getLineColor: (d) => DIFF_COLOR[d.cls],
      lineWidthMinPixels: 1.25,
    }),
    new IconLayer<{ cls: DiffClass; node: GraphNode }>({
      id: "diff-added",
      data: items.filter((d) => d.cls === "added"),
      iconAtlas: atlas.url,
      iconMapping: atlas.mapping,
      getIcon: (d) => glyphForNode(d.node),
      getPosition: (d) => pos(d.node),
      getSize: 16,
      sizeUnits: "pixels",
      getColor: WHITE,
      pickable: true,
    }),
  ];
}

// ------------------------------------------------------------------ animated layers

export interface DroneInput {
  tracks: Track[];
  origin: number; // epoch s subtracted from timestamps (float32 precision on the GPU)
  relTimestamps: number[][];
  time: number;
  overlay: Overlay;
  atlas: IconAtlas;
  nodeIndex: ReadonlyMap<string, GraphNode>;
}

export function buildDroneLayers(d: DroneInput): Layer[] {
  const heads = d.tracks.flatMap((t) => {
    const p = clampedPositionAt(t, d.time);
    const node = d.nodeIndex.get(t.id);
    return p && node ? [{ node, p }] : [];
  });
  return [
    new TripsLayer<Track>({
      id: "drone-trails",
      data: d.tracks,
      getPath: (t) => t.path,
      getTimestamps: (_t, { index }) => d.relTimestamps[index] ?? [],
      currentTime: d.time - d.origin,
      trailLength: DRONE_TRAIL_S,
      fadeTrail: true,
      getColor: TRAIL,
      widthMinPixels: 1.25,
      capRounded: true,
      jointRounded: true,
    }),
    new IconLayer<{ node: GraphNode; p: { lon: number; lat: number; headingDeg: number } }>({
      id: "drone-heads",
      data: heads,
      iconAtlas: d.atlas.url,
      iconMapping: d.atlas.mapping,
      getIcon: () => "drone",
      getPosition: (h) => [h.p.lon, h.p.lat],
      getAngle: (h) => -h.p.headingDeg,
      getSize: 15,
      sizeUnits: "pixels",
      getColor: (h) => nodeColor(h.node, statusOf(d.overlay, h.node.id)),
      pickable: true,
    }),
  ];
}

export interface StrikeInput {
  trips: ArcTrip[];
  elapsedMs: number;
  struck: GraphNode;
  arrivals: Map<string, number>;
  targets: GraphNode[];
  reducedMotion: boolean;
}

export function buildStrikeLayers(s: StrikeInput): Layer[] {
  const out: Layer[] = [
    new TripsLayer<ArcTrip>({
      id: "strike-arcs",
      data: s.trips,
      getPath: (t) => t.path,
      getTimestamps: (t) => t.timestamps,
      currentTime: s.elapsedMs,
      trailLength: 1e9,
      fadeTrail: false,
      getColor: withAlpha(ARC, 0.85),
      widthMinPixels: 1.75,
      capRounded: true,
      jointRounded: true,
    }),
  ];
  const popped = s.targets.filter((n) => (s.arrivals.get(n.id) ?? 0) <= s.elapsedMs);
  out.push(
    new ScatterplotLayer<GraphNode>({
      id: "impact-pop",
      data: popped,
      getPosition: pos,
      getRadius: (n) => {
        const since = s.elapsedMs - (s.arrivals.get(n.id) ?? 0);
        const k = s.reducedMotion ? 1 : Math.min(1, since / IMPACT_POP_MS);
        return 6 + 8 * (1 - (1 - k) ** 3);
      },
      radiusUnits: "pixels",
      stroked: true,
      filled: false,
      getLineColor: withAlpha(AMBER, 0.9),
      lineWidthMinPixels: 1.25,
      updateTriggers: { getRadius: s.elapsedMs },
    }),
  );
  if (located(s.struck) && !s.reducedMotion && s.elapsedMs < SHOCKWAVE_MS) {
    const k = s.elapsedMs / SHOCKWAVE_MS;
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "shockwave",
        data: [s.struck],
        getPosition: pos,
        getRadius: 8 + 70 * (1 - (1 - k) ** 3),
        radiusUnits: "pixels",
        stroked: true,
        filled: false,
        getLineColor: withAlpha(RED, 1 - k),
        lineWidthMinPixels: 2,
        updateTriggers: { getRadius: s.elapsedMs, getLineColor: s.elapsedMs },
      }),
    );
  }
  if (located(s.struck)) {
    out.push(
      new TextLayer<GraphNode>({
        id: "struck-label",
        data: [s.struck],
        getPosition: pos,
        getText: (n) => `${n.name.toUpperCase()} · LOST`,
        getSize: 12,
        sizeUnits: "pixels",
        getColor: RED,
        getPixelOffset: [0, -24],
        fontFamily: LABEL_FONT,
        fontWeight: 600,
        characterSet: "auto",
        outlineWidth: 3,
        outlineColor: [7, 11, 18, 255],
        fontSettings: { sdf: true },
      }),
    );
  }
  return out;
}

export function buildPulseLayer(pulses: Pulse[], now: number, durationMs: number): Layer | null {
  const live = pulses.filter((p) => now - p.at < durationMs);
  if (!live.length) return null;
  return new ScatterplotLayer<Pulse>({
    id: "report-pulses",
    data: live,
    getPosition: (p) => [p.lon, p.lat],
    getPixelOffset: REPORT_OFFSET,
    getRadius: (p) => 8 + PULSE_MAX_PX * ((now - p.at) / durationMs),
    radiusUnits: "pixels",
    stroked: true,
    filled: false,
    getLineColor: (p) => withAlpha(WHITE, 0.9 * (1 - (now - p.at) / durationMs)),
    lineWidthMinPixels: 1.5,
    updateTriggers: { getRadius: now, getLineColor: now },
  });
}

/** Normalise any picked object to the GraphNode it represents. */
export function pickedNode(info: PickingInfo): GraphNode | null {
  const obj = info.object as unknown;
  if (!obj || typeof obj !== "object") return null;
  if ("node" in obj && obj.node && typeof obj.node === "object") return obj.node as GraphNode;
  if ("id" in obj && "kind" in obj) return obj as GraphNode;
  return null;
}
