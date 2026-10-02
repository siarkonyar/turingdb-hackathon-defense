import { GLYPHS, STROKE_WIDTH, type GlyphName } from "../lib/glyphs";

interface GlyphProps {
  name: GlyphName;
  size?: number;
  color?: string;
  title?: string;
}

export function Glyph({ name, size = 16, color = "currentColor", title }: GlyphProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      style={{ flex: "none", display: "block" }}
    >
      {GLYPHS[name].map((part, i) =>
        part.mode === "fill" ? (
          <path key={i} d={part.d} fill={color} />
        ) : (
          <path
            key={i}
            d={part.d}
            fill="none"
            stroke={color}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ),
      )}
    </svg>
  );
}
