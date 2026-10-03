// Pure helpers for the Dover exercise chat and its recovery overlay: one colour per recovery state and link
// kind (map, legend and report share them), number formatting and the map focus for a recovery result.

import type { ExerciseMetrics, RecoveryLinkKind, RecoveryState } from "../api/types";
import type { RGBA } from "../map/colors";

export const STATE_COLORS: Record<RecoveryState, RGBA> = {
  lost: [235, 72, 76, 255], // physically down: red
  relocated: [61, 139, 240, 255], // service continues elsewhere: blue
  restored: [74, 196, 140, 255], // back to full service: green
  improved: [236, 204, 58, 255], // better, still short: yellow
  residual: [245, 140, 35, 255], // still affected: orange
};

export const STATE_LABELS: Record<RecoveryState, string> = {
  lost: "Disrupted / lost",
  relocated: "Relocated service",
  restored: "Restored service",
  improved: "Partly restored",
  residual: "Residual risk",
};

export const LINK_COLORS: Record<RecoveryLinkKind, RGBA> = {
  route: [255, 255, 255, 255],
  power: [250, 214, 80, 255],
  stock: [178, 140, 255, 255],
  relocation: [61, 139, 240, 255],
  export: [56, 189, 212, 255],
};

export const LINK_LABELS: Record<RecoveryLinkKind, string> = {
  route: "Recovery route",
  power: "Generator allocation",
  stock: "Reserve release",
  relocation: "Relocation",
  export: "Second-source export",
};

export const STATE_ORDER: RecoveryState[] = ["lost", "relocated", "restored", "improved", "residual"];

export const css = ([r, g, b]: RGBA) => `rgb(${r} ${g} ${b})`;

export const pct = (x: number) => `${(100 * x).toFixed(1)}%`;

export const tonnes = (t: number) => `${Math.round(t).toLocaleString("en-GB")} t`;

export const hours = (h: number | null | undefined) => (h == null ? "never" : `+${h.toLocaleString("en-GB")} h`);

/** Signed change in percentage points between two fractions, e.g. "+56.0 pp". */
export function deltaPp(before: number, after: number): string {
  const d = 100 * (after - before);
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)} pp`;
}

export interface MetricRow {
  label: string;
  before: string;
  after: string;
  better: boolean | null; // null: unchanged or neutral
}

const cmp = (x: number, y: number, higherIsBetter: boolean) => (x === y ? null : higherIsBetter ? y > x : y < x);

/** The before/after report rows, all measured by the simulator. */
export function metricRows(b: ExerciseMetrics, a: ExerciseMetrics): MetricRow[] {
  return [
    { label: "Essential demand fulfilment", before: pct(b.essential_fulfilment), after: pct(a.essential_fulfilment),
      better: cmp(b.essential_fulfilment, a.essential_fulfilment, true) },
    { label: "All demand fulfilment", before: pct(b.overall_fulfilment), after: pct(a.overall_fulfilment),
      better: cmp(b.overall_fulfilment, a.overall_fulfilment, true) },
    { label: "Cargo on time", before: tonnes(b.cargo_on_time_t), after: tonnes(a.cargo_on_time_t),
      better: cmp(b.cargo_on_time_t, a.cargo_on_time_t, true) },
    { label: "Cargo delayed", before: tonnes(b.cargo_delayed_t), after: tonnes(a.cargo_delayed_t), better: null },
    { label: "Cargo unmet", before: tonnes(b.cargo_unmet_t), after: tonnes(a.cargo_unmet_t),
      better: cmp(b.cargo_unmet_t, a.cargo_unmet_t, false) },
    { label: "Demands below minimum", before: String(b.demands_below_minimum), after: String(a.demands_below_minimum),
      better: cmp(b.demands_below_minimum, a.demands_below_minimum, false) },
    { label: "Capabilities below 80%", before: `${b.capabilities_below_minimum}/${b.capabilities_total}`,
      after: `${a.capabilities_below_minimum}/${a.capabilities_total}`,
      better: cmp(b.capabilities_below_minimum, a.capabilities_below_minimum, false) },
    { label: "Facilities affected at end", before: String(b.affected_at_end), after: String(a.affected_at_end),
      better: cmp(b.affected_at_end, a.affected_at_end, false) },
  ];
}

/** One colour per recovery step group, matching its links on the map. */
export function groupColor(key: string): RGBA {
  if (key.startsWith("reroute:")) return LINK_COLORS.route;
  if (key === "islanded_power" || key === "mobile_power") return LINK_COLORS.power;
  if (key === "release_stock") return LINK_COLORS.stock;
  if (key === "second_source") return LINK_COLORS.export;
  return LINK_COLORS.relocation;
}
