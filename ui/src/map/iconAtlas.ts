// Rasterises GLYPHS into one white mask atlas for deck.gl IconLayers (tinted per object via getColor).

import { GLYPHS, STROKE_WIDTH, type GlyphName } from "../lib/glyphs";

export interface IconDef {
  x: number;
  y: number;
  width: number;
  height: number;
  mask: boolean;
  anchorX: number;
  anchorY: number;
}

export interface IconAtlas {
  url: string;
  mapping: Record<GlyphName, IconDef>;
}

const CELL = 64; // px per glyph: crisp at 2x DPR for 26px glyphs
const COLUMNS = 6;

export function buildIconAtlas(): IconAtlas {
  const names = Object.keys(GLYPHS) as GlyphName[];
  const rows = Math.ceil(names.length / COLUMNS);
  const canvas = document.createElement("canvas");
  canvas.width = CELL * COLUMNS;
  canvas.height = CELL * rows;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D canvas unavailable: cannot build icon atlas");
  const scale = CELL / 24;
  const mapping = {} as Record<GlyphName, IconDef>;

  names.forEach((name, i) => {
    const x = (i % COLUMNS) * CELL;
    const y = Math.floor(i / COLUMNS) * CELL;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = STROKE_WIDTH;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const part of GLYPHS[name]) {
      const path = new Path2D(part.d);
      if (part.mode === "fill") ctx.fill(path);
      else ctx.stroke(path);
    }
    ctx.restore();
    mapping[name] = { x, y, width: CELL, height: CELL, mask: true, anchorX: CELL / 2, anchorY: CELL / 2 };
  });

  return { url: canvas.toDataURL("image/png"), mapping };
}
