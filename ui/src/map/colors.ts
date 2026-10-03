// Colour only means something: amber = selected / at risk, red = lost, white = appeared (diff),
// blue = defended (a wargame countermeasure).
// Everything else is a desaturated grey, brighter for more important asset types.

import type { GraphNode, Kind, Status } from "../api/types";

export type RGBA = [number, number, number, number];

export const AMBER: RGBA = [245, 166, 35, 255];
export const RED: RGBA = [235, 72, 76, 255];
export const WHITE: RGBA = [244, 247, 251, 255];
export const BLUE: RGBA = [61, 139, 240, 255]; // #3d8bf0, validated against RED on the dark surface

const NEUTRAL: Record<Kind, RGBA> = {
  plant: [146, 158, 175, 190],
  site: [236, 240, 246, 255],
  supplier: [196, 204, 216, 240],
  facility: [168, 180, 196, 215],
  port: [208, 216, 228, 240],
  chokepoint: [120, 200, 255, 255],
  drone: [214, 220, 229, 240],
  crime: [120, 130, 146, 150],
  report: [226, 232, 240, 235],
  part: [150, 161, 176, 200],
  other: [150, 161, 176, 200],
};

export const CYBER_RING: RGBA = [160, 172, 190, 70];
export const TRAIL: RGBA = [190, 200, 214, 110];
export const ARC: RGBA = AMBER;

export function statusColor(status: Status | null | undefined): RGBA | null {
  if (status === "lost" || status === "no_power") return RED;
  if (status === "at_risk") return AMBER;
  return null;
}

export function nodeColor(node: Pick<GraphNode, "kind">, status: Status | null | undefined, dimmed = false): RGBA {
  const c = statusColor(status) ?? NEUTRAL[node.kind];
  return dimmed ? [c[0], c[1], c[2], Math.round(c[3] * 0.35)] : c;
}

export function withAlpha(c: RGBA, alpha: number): RGBA {
  return [c[0], c[1], c[2], Math.round(Math.max(0, Math.min(1, alpha)) * 255)];
}

export const CSS = {
  amber: "rgb(245 166 35)",
  red: "rgb(235 72 76)",
  white: "rgb(244 247 251)",
  blue: "rgb(61 139 240)",
} as const;
