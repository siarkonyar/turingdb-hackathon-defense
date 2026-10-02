import { formatIso, formatMw, formatPercent } from "../lib/format";
import { glyphForNode } from "../lib/glyphs";
import { activeOverlay, useOps } from "../state/store";
import { Glyph } from "./Glyph";
import { StatusChip } from "./StatusChip";

export function HoverCard() {
  const hover = useOps((s) => s.hover);
  const status = useOps((s) => (s.hover ? activeOverlay(s).entries.get(s.hover.node.id)?.status : undefined));
  const menuOpen = useOps((s) => s.contextMenu !== null);
  if (!hover || menuOpen) return null;
  const { node } = hover;
  const detail =
    node.kind === "plant"
      ? `${node.fuel ?? "Plant"} · ${formatMw(node.capacity_mw)}`
      : node.kind === "report"
        ? `${formatIso(node.timestamp)} · conf ${formatPercent(node.confidence)}`
        : node.kind === "crime"
          ? formatIso(node.timestamp)
          : node.label;
  return (
    <div className="hovercard glass" style={{ left: hover.x + 14, top: hover.y + 14 }} role="tooltip">
      <div className="hovercard__title">
        <Glyph name={glyphForNode(node)} size={14} />
        <span>{node.name}</span>
      </div>
      <div className="hovercard__meta mono">
        {detail}
        {status ? <StatusChip status={status} /> : null}
      </div>
    </div>
  );
}
