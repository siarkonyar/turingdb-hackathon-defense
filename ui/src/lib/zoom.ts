// Zoom-based filtering for the 35k power plants: at continental zoom only large plants are drawn,
// smaller ones appear as you zoom in. Runs on the GPU via deck.gl's DataFilterExtension.

export const FULL_DETAIL_ZOOM = 8;
const CAPACITY_AT_ZOOM_2_MW = 2400;
const HALVINGS_PER_ZOOM = 1.45;

/** Minimum capacity (MW) for a plant to be drawn at this zoom; 0 = everything. */
export function minCapacityForZoom(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom >= FULL_DETAIL_ZOOM) return 0;
  const z = Math.max(zoom, 2);
  return Math.round(CAPACITY_AT_ZOOM_2_MW * 0.5 ** ((z - 2) * HALVINGS_PER_ZOOM));
}

/** Plants with a status (at risk / lost) or the selection are always visible. */
export const ALWAYS_VISIBLE = 1e9;

export function filterValue(capacity: number | null | undefined, pinned: boolean): number {
  return pinned ? ALWAYS_VISIBLE : (capacity ?? 0);
}

/** Pixel size for a glyph given its 0..1 importance. */
export function glyphSize(importance: number, min = 9, max = 26): number {
  const t = Math.min(1, Math.max(0, importance));
  return min + (max - min) * t;
}
