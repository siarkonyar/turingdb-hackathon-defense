// Wargame move choreography, rebuilt per animation frame while it plays:
//   red    - shockwave rings on the struck targets, then cascade arcs to the newly affected nodes
//   blue   - slow pulses on the protected / re-powered assets, arcs to the nodes they restored
//   inject - amber rings over the event footprint

import { TripsLayer } from "@deck.gl/geo-layers";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";

import type { MoveTarget } from "../api/types";
import { arcTrips, type ArcTrip } from "../lib/arcs";
import type { MatchFx } from "../state/store";
import { AMBER, BLUE, RED, withAlpha, type RGBA } from "./colors";

export const MATCH_FX_MS = 3600;
const RING_MS = 1200;
const RINGS = 3;
const RING_GAP_MS = 380;
const RING_MAX_PX = 54;
const LABEL_FONT = "Inter Variable, Inter, system-ui, sans-serif";
const LABEL_LIMIT = 3;

const COLOR: Record<MatchFx["side"], RGBA> = { red: RED, blue: BLUE, inject: AMBER };
const VERB: Record<MatchFx["side"], string> = { red: "STRUCK", blue: "DEFENDED", inject: "EVENT" };

interface Ring {
  target: MoveTarget;
  k: number; // 0..1 progress of this ring
}

export function matchFxActive(fx: MatchFx | null, now: number): boolean {
  return Boolean(fx) && now - (fx as MatchFx).startedAt < MATCH_FX_MS;
}

export function buildMatchFxLayers(fx: MatchFx, now: number, reducedMotion: boolean): Layer[] {
  const elapsed = now - fx.startedAt;
  const color = COLOR[fx.side];
  const fade = Math.max(0, 1 - Math.max(0, elapsed - (MATCH_FX_MS - 600)) / 600);
  const targets = fx.targets.filter((t) => Number.isFinite(t.lat) && Number.isFinite(t.lon));
  const rings: Ring[] = [];
  if (!reducedMotion) {
    for (let i = 0; i < RINGS; i += 1) {
      const k = (elapsed - i * RING_GAP_MS) / RING_MS;
      if (k > 0 && k < 1) for (const target of targets) rings.push({ target, k });
    }
  }
  const { trips } = arcTrips(fx.arcs, reducedMotion);
  const arcStart = fx.side === "red" ? 350 : 0; // the strike lands first, then the cascade spreads
  const layers: Layer[] = [
    new ScatterplotLayer<MoveTarget>({
      id: "match-fx-core",
      data: targets,
      getPosition: (t) => [t.lon, t.lat],
      getRadius: 7,
      radiusUnits: "pixels",
      getFillColor: withAlpha(color, 0.85 * fade),
      stroked: true,
      getLineColor: withAlpha([7, 11, 18, 255], fade),
      lineWidthMinPixels: 2,
      updateTriggers: { getFillColor: fade, getLineColor: fade },
    }),
    new ScatterplotLayer<Ring>({
      id: "match-fx-rings",
      data: rings,
      getPosition: (r) => [r.target.lon, r.target.lat],
      getRadius: (r) => 8 + RING_MAX_PX * (1 - (1 - r.k) ** 3),
      radiusUnits: "pixels",
      stroked: true,
      filled: false,
      getLineColor: (r) => withAlpha(color, 1 - r.k),
      lineWidthMinPixels: fx.side === "red" ? 2 : 1.5,
      updateTriggers: { getRadius: elapsed, getLineColor: elapsed },
    }),
    new TripsLayer<ArcTrip>({
      id: "match-fx-arcs",
      data: trips,
      getPath: (t) => t.path,
      getTimestamps: (t) => t.timestamps,
      currentTime: reducedMotion ? Number.MAX_SAFE_INTEGER : Math.max(0, elapsed - arcStart),
      trailLength: 1e9,
      fadeTrail: false,
      getColor: withAlpha(fx.side === "red" ? AMBER : color, 0.85 * fade),
      widthMinPixels: 1.5,
      capRounded: true,
      jointRounded: true,
      updateTriggers: { getColor: fade },
    }),
    new TextLayer<MoveTarget>({
      id: "match-fx-labels",
      data: targets.slice(0, LABEL_LIMIT),
      getPosition: (t) => [t.lon, t.lat],
      getText: (t) => `${t.name.toUpperCase()} · ${VERB[fx.side]}`,
      getSize: 12,
      sizeUnits: "pixels",
      getColor: withAlpha(color, fade),
      getPixelOffset: [0, -22],
      fontFamily: LABEL_FONT,
      fontWeight: 600,
      characterSet: "auto",
      outlineWidth: 3,
      outlineColor: [7, 11, 18, 255],
      fontSettings: { sdf: true },
      updateTriggers: { getColor: fade },
    }),
  ];
  return layers;
}
