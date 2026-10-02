// Branch state as seen by the map: which nodes are at risk / lost on the active branch.
// Built from GET /diff?a=main&b=<branch>, and merged with POST /simulate results.

import type { DiffResponse, GraphNode, Kpis, SimulateResponse, Status } from "../api/types";

export interface OverlayEntry {
  status: Status;
  node: GraphNode;
}

export interface Overlay {
  entries: ReadonlyMap<string, OverlayEntry>;
  added: readonly GraphNode[];
}

export const EMPTY_OVERLAY: Overlay = { entries: new Map(), added: [] };

const RANK: Record<Status, number> = { at_risk: 1, no_power: 2, lost: 3 };

export function escalate(prev: Status | undefined, next: Status): Status {
  return prev && RANK[prev] >= RANK[next] ? prev : next;
}

function isStatus(value: unknown): value is Status {
  return value === "at_risk" || value === "lost" || value === "no_power";
}

export function overlayFromDiff(diff: DiffResponse): Overlay {
  const entries = new Map<string, OverlayEntry>();
  for (const node of diff.removed) entries.set(node.id, { status: "lost", node });
  for (const change of diff.changed) {
    const status = change.fields.status?.[1];
    if (isStatus(status)) entries.set(change.node.id, { status, node: change.node });
  }
  return { entries, added: diff.added };
}

export function mergeSimulation(base: Overlay, sim: SimulateResponse): Overlay {
  const entries = new Map(base.entries);
  const put = (node: GraphNode, status: Status) =>
    entries.set(node.id, { status: escalate(entries.get(node.id)?.status, status), node });
  put(sim.struck, "lost");
  for (const a of sim.affected) put(a.node, a.node.status ?? "at_risk");
  return { entries, added: base.added };
}

const located = (n: GraphNode) => n.lat != null && n.lon != null;

export function kpisFromOverlay(overlay: Overlay): Kpis {
  let atRisk = 0;
  let sites = 0;
  let suppliers = 0;
  let parts = 0;
  for (const { status, node } of overlay.entries.values()) {
    if (node.label === "Part") parts += 1;
    else if (status === "at_risk" && located(node)) atRisk += 1;
    else if (status === "no_power" && node.label === "Site") sites += 1;
    else if (status === "no_power" && node.label === "Supplier") suppliers += 1;
  }
  return { assets_at_risk: atRisk, sites_without_power: sites, suppliers_without_power: suppliers, parts_affected: parts };
}

export type DiffClass = "added" | "removed" | "changed";

export function diffClasses(diff: DiffResponse): Map<string, { cls: DiffClass; node: GraphNode }> {
  const out = new Map<string, { cls: DiffClass; node: GraphNode }>();
  for (const n of diff.added) out.set(n.id, { cls: "added", node: n });
  for (const n of diff.removed) out.set(n.id, { cls: "removed", node: n });
  for (const c of diff.changed) out.set(c.node.id, { cls: "changed", node: c.node });
  return out;
}
