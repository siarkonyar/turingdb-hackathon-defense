// One small geometric glyph per asset type (plants by fuel), defined once as SVG paths in a
// 24x24 box. The map's icon atlas and the React <Glyph/> both draw from this table.

import type { GraphNode } from "../api/types";

export interface GlyphPart {
  d: string;
  mode: "fill" | "stroke";
}

export type GlyphName =
  | "plant-nuclear"
  | "plant-coal"
  | "plant-gas"
  | "plant-oil"
  | "plant-hydro"
  | "plant-wind"
  | "plant-solar"
  | "plant-bio"
  | "plant-geo"
  | "plant-storage"
  | "plant-other"
  | "site"
  | "supplier"
  | "drone"
  | "report"
  | "crime"
  | "cyber"
  | "lost";

const C = 12;

function circle(r: number, cx = C, cy = C): string {
  return `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
}

function polar(r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180;
  return [C + r * Math.cos(a), C + r * Math.sin(a)];
}

function wedge(r0: number, r1: number, a0: number, a1: number): string {
  const [x0, y0] = polar(r1, a0);
  const [x1, y1] = polar(r1, a1);
  const [x2, y2] = polar(r0, a1);
  const [x3, y3] = polar(r0, a0);
  return `M${x0} ${y0}A${r1} ${r1} 0 0 1 ${x1} ${y1}L${x2} ${y2}A${r0} ${r0} 0 0 0 ${x3} ${y3}Z`;
}

function polygon(points: [number, number][]): string {
  return `M${points.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join("L")}Z`;
}

function regular(sides: number, r: number, rotDeg = 0): string {
  return polygon(Array.from({ length: sides }, (_, i) => polar(r, rotDeg + (360 / sides) * i)));
}

function rays(count: number, r0: number, r1: number): string {
  return Array.from({ length: count }, (_, i) => {
    const [x0, y0] = polar(r0, (360 / count) * i);
    const [x1, y1] = polar(r1, (360 / count) * i);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)}L${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }).join("");
}

export const GLYPHS: Record<GlyphName, GlyphPart[]> = {
  "plant-nuclear": [
    { d: [0, 120, 240].map((a) => wedge(3, 9, a - 30, a + 30)).join(""), mode: "fill" },
    { d: circle(1.8), mode: "fill" },
  ],
  "plant-coal": [{ d: "M6.5 6.5h11v11h-11Z", mode: "fill" }],
  "plant-gas": [{ d: regular(4, 8), mode: "fill" }],
  "plant-oil": [{ d: regular(4, 7.5), mode: "stroke" }],
  "plant-hydro": [{ d: "M12 3.5C12 3.5 6 10.5 6 14.5a6 6 0 0 0 12 0C18 10.5 12 3.5 12 3.5Z", mode: "fill" }],
  "plant-wind": [
    { d: rays(3, 1.6, 9.5), mode: "stroke" },
    { d: circle(1.6), mode: "fill" },
  ],
  "plant-solar": [
    { d: circle(4), mode: "fill" },
    { d: rays(8, 6.5, 9.5), mode: "stroke" },
  ],
  "plant-bio": [{ d: "M6 18C6 10 11 5.5 18.5 5.5C18.5 13 14 18 6 18Z", mode: "fill" }],
  "plant-geo": [{ d: "M5 16.5L12 7.5L19 16.5", mode: "stroke" }],
  "plant-storage": [
    { d: "M5.5 8h11.5v8h-11.5Z", mode: "stroke" },
    { d: "M18.5 10.5h1.5v3h-1.5Z", mode: "fill" },
  ],
  "plant-other": [
    { d: circle(7), mode: "stroke" },
    { d: circle(2), mode: "fill" },
  ],
  site: [
    { d: regular(6, 9.5), mode: "stroke" },
    { d: regular(6, 4.5), mode: "fill" },
  ],
  supplier: [{ d: regular(3, 9, 0), mode: "stroke" }],
  drone: [{ d: "M12 3L19 19L12 15L5 19Z", mode: "fill" }],
  report: [
    { d: "M6.5 4.5h7.5l4 4v11h-11.5Z", mode: "stroke" },
    { d: "M9.5 12h5M9.5 15h5", mode: "stroke" },
  ],
  crime: [{ d: "M8 8L16 16M16 8L8 16", mode: "stroke" }],
  cyber: [
    { d: circle(8.5), mode: "stroke" },
    { d: circle(4), mode: "stroke" },
  ],
  lost: [{ d: "M6 6L18 18M18 6L6 18", mode: "stroke" }],
};

const FUEL_GLYPH: Record<string, GlyphName> = {
  Nuclear: "plant-nuclear",
  Coal: "plant-coal",
  Petcoke: "plant-coal",
  Gas: "plant-gas",
  Oil: "plant-oil",
  Hydro: "plant-hydro",
  "Wave and Tidal": "plant-hydro",
  Wind: "plant-wind",
  Solar: "plant-solar",
  Biomass: "plant-bio",
  Waste: "plant-bio",
  Geothermal: "plant-geo",
  Storage: "plant-storage",
};

export function glyphForFuel(fuel: string | null | undefined): GlyphName {
  return (fuel && FUEL_GLYPH[fuel]) || "plant-other";
}

export function glyphForNode(node: Pick<GraphNode, "kind" | "fuel">): GlyphName {
  switch (node.kind) {
    case "plant":
      return glyphForFuel(node.fuel);
    case "site":
    case "supplier":
    case "drone":
    case "report":
    case "crime":
      return node.kind;
    default:
      return "plant-other";
  }
}

export const STROKE_WIDTH = 2;
