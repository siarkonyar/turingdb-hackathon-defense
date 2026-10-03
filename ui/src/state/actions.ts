// Async actions: every API call goes through here so latency, errors and toasts are uniform.

import { api, ApiError, eventsUrl } from "../api/client";
import { follow, JOB_EVENTS } from "../api/sse";
import type { GraphNode, JobEvent, ScenarioResponse, Timed } from "../api/types";
import { EMPTY_OVERLAY, mergeSimulation, overlayFromDiff } from "../lib/overlay";
import { prefersReducedMotion } from "../lib/motion";
import { newlyArrived, timelineDomain } from "../lib/time";
import { setOps, useOps, type BaseKind, type LayerKey, type Toast } from "./store";

const TOAST_MS = 4200;
const PULSE_MS = 1600;
const FLY_ZOOM = 9;
const BASE_KINDS: BaseKind[] = ["site", "supplier", "facility", "port", "drone", "crime", "plant"];
const STRIKABLE = new Set(["plant", "site", "supplier", "facility", "port", "drone"]);

let toastSeq = 0;
let flySeq = 0;

export function toast(text: string, tone: Toast["tone"] = "info"): void {
  const id = ++toastSeq;
  setOps((s) => ({ toasts: [...s.toasts, { id, text, tone }].slice(-4) }));
  window.setTimeout(() => setOps((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), TOAST_MS);
}

export function message(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : String(err);
}

export function recordLatency(op: string, timed: Timed): void {
  setOps({
    latency: {
      op,
      ms: timed.latency_ms,
      roundtripMs: timed.roundtrip_ms,
      engine: timed.engine,
      queries: timed.queries?.length ?? 0,
    },
  });
}

function indexNodes(groups: GraphNode[][]): Map<string, GraphNode> {
  const index = new Map<string, GraphNode>();
  for (const group of groups) for (const n of group) index.set(n.id, n);
  return index;
}

export async function bootstrap(): Promise<void> {
  try {
    const [meta, branches, reports, tracks, ...kinds] = await Promise.all([
      api.meta(),
      api.branches(),
      api.reports(),
      api.tracks(),
      ...BASE_KINDS.map((k) => api.nodes([k])),
    ]);
    const base = Object.fromEntries(BASE_KINDS.map((k, i) => [k, kinds[i]?.nodes ?? []])) as Record<
      BaseKind,
      GraphNode[]
    >;
    const commits = branches.branches.find((b) => b.id === "main")?.commits ?? [];
    const domain = timelineDomain(reports.reports, tracks.tracks, commits);
    const plants = kinds[BASE_KINDS.indexOf("plant")];
    setOps({
      phase: "ready",
      meta,
      base,
      nodeIndex: indexNodes([...Object.values(base), reports.reports.map((r) => r.node)]),
      reports: reports.reports,
      tracks: tracks.tracks,
      branches: branches.branches,
      domain,
      time: domain ? domain[1] : 0,
    });
    if (plants) recordLatency(`load ${plants.nodes.length.toLocaleString("en-GB")} plants`, plants);
  } catch (err) {
    setOps({ phase: "error", error: message(err) });
  }
}

export function toggleLayer(key: LayerKey): void {
  setOps((s) => ({ layers: { ...s.layers, [key]: !s.layers[key] } }));
}

export function flyToNode(node: GraphNode, zoom?: number): void {
  if (node.lat == null || node.lon == null) return;
  setOps({ flyTo: { lon: node.lon, lat: node.lat, zoom, nonce: ++flySeq } });
}

export async function selectNode(node: GraphNode, opts: { fly?: boolean } = {}): Promise<void> {
  const { activeBranch, overlays } = useOps.getState();
  if (opts.fly) flyToNode(node, Math.max(FLY_ZOOM, 0));
  setOps({ drawer: { nodeId: node.id, loading: true, data: null, error: null, note: null }, contextMenu: null });
  const lostHere = overlays[activeBranch]?.entries.get(node.id)?.status === "lost";
  const branch = lostHere ? "main" : activeBranch;
  try {
    const data = await api.neighbours(node.id, branch);
    if (useOps.getState().drawer?.nodeId !== node.id) return; // a newer selection won
    recordLatency("neighbours", data);
    const note = lostHere ? "Lost on this branch, showing its last state on main." : null;
    setOps({ drawer: { nodeId: node.id, loading: false, data, error: null, note } });
  } catch (err) {
    if (useOps.getState().drawer?.nodeId !== node.id) return;
    setOps({ drawer: { nodeId: node.id, loading: false, data: null, error: message(err), note: null } });
  }
}

export function closeDrawer(): void {
  setOps({ drawer: null });
}

export async function refreshBranches(): Promise<void> {
  try {
    const resp = await api.branches();
    setOps({ branches: resp.branches });
  } catch (err) {
    toast(`Could not refresh branches: ${message(err)}`, "error");
  }
}

export function canStrike(node: GraphNode): boolean {
  return STRIKABLE.has(node.kind);
}

export async function simulateLoss(node: GraphNode): Promise<void> {
  const state = useOps.getState();
  const active = state.branches.find((b) => b.id === state.activeBranch);
  const stacking = active?.kind === "strike";
  const base = stacking ? state.activeBranch : "main";
  if (active && !stacking && active.kind !== "main") {
    toast(`${active.label} is read-only; the strike branches from main.`, "warn");
  }
  setOps({ busy: `Simulating loss of ${node.name}`, contextMenu: null });
  try {
    const sim = await api.simulate(node.id, base);
    recordLatency("cascade", sim);
    setOps((s) => ({
      overlays: { ...s.overlays, [sim.branch]: mergeSimulation(stacking ? (s.overlays[base] ?? EMPTY_OVERLAY) : EMPTY_OVERLAY, sim) },
      activeBranch: sim.branch,
      strike: { sim, startedAt: performance.now() },
      diff: null,
      diffOpen: false,
    }));
    const k = sim.kpis;
    toast(
      `${node.name} lost: ${k.assets_at_risk} assets at risk, ${k.sites_without_power} sites without power, ` +
        `${k.parts_affected} parts affected.`,
    );
    await refreshBranches();
  } catch (err) {
    toast(`Simulation failed: ${message(err)}`, "error");
  } finally {
    setOps({ busy: null });
  }
}

export async function switchBranch(branchId: string): Promise<void> {
  setOps({ branchMenuOpen: false });
  const { overlays } = useOps.getState();
  if (branchId === "main" || overlays[branchId]) {
    setOps({ activeBranch: branchId, strike: null });
    return;
  }
  setOps({ busy: "Loading branch" });
  try {
    const diff = await api.diff("main", branchId);
    recordLatency(`diff main→${branchId}`, diff);
    setOps((s) => ({ overlays: { ...s.overlays, [branchId]: overlayFromDiff(diff) }, activeBranch: branchId, strike: null }));
  } catch (err) {
    toast(`Could not load branch ${branchId}: ${message(err)}`, "error");
  } finally {
    setOps({ busy: null });
  }
}

export async function discardBranch(branchId: string): Promise<void> {
  try {
    await api.discard(branchId);
    setOps((s) => {
      const overlays = Object.fromEntries(Object.entries(s.overlays).filter(([id]) => id !== branchId));
      return {
        overlays,
        activeBranch: s.activeBranch === branchId ? "main" : s.activeBranch,
        strike: s.strike?.sim.branch === branchId ? null : s.strike,
      };
    });
    await refreshBranches();
  } catch (err) {
    toast(`Could not discard branch: ${message(err)}`, "error");
  }
}

export async function runDiff(a: string, b: string): Promise<void> {
  setOps({ diff: { a, b, result: null, loading: true }, diffOpen: true });
  try {
    const result = await api.diff(a, b);
    recordLatency("diff", result);
    setOps({ diff: { a, b, result, loading: false } });
  } catch (err) {
    setOps({ diff: null });
    toast(`Diff failed: ${message(err)}`, "error");
  }
}

export function clearDiff(): void {
  setOps({ diff: null });
}

function patchScenario(patch: Partial<import("./store").ScenarioState>): void {
  setOps((s) => ({ scenario: { ...s.scenario, ...patch } }));
}

export function setScenarioOpen(open: boolean): void {
  patchScenario({ open });
  if (open && useOps.getState().scenario.status === null) {
    void api
      .agentStatus()
      .then((status) => patchScenario({ status }))
      .catch(() => patchScenario({ status: { available: false, reason: "agent status unavailable" } }));
  }
}

export function setScenarioQuestion(question: string): void {
  patchScenario({ question });
}

export async function askScenario(): Promise<void> {
  const question = useOps.getState().scenario.question.trim();
  if (!question) return;
  patchScenario({ loading: true, error: null, explanation: null, branch: null, steps: [], thought: null, impact: null, deep: null });
  try {
    const { job_id } = await api.agentScenario(question);
    follow<JobEvent>(
      eventsUrl("job", job_id),
      JOB_EVENTS,
      (ev) => void onScenarioEvent(ev),
      (why) => patchScenario({ loading: false, error: why }),
    );
  } catch (err) {
    patchScenario({ loading: false, error: message(err) });
    toast(`Scenario failed: ${message(err)}`, "error");
  }
}

async function onScenarioEvent(ev: JobEvent): Promise<void> {
  if (ev.type === "step") {
    setOps((s) => ({ scenario: { ...s.scenario, steps: [...s.scenario.steps, ev.action], thought: ev.thought || s.scenario.thought } }));
  } else if (ev.type === "error") {
    patchScenario({ loading: false, error: ev.message });
    toast(`Scenario failed: ${ev.message}`, "error");
  } else if (ev.type === "done") {
    if (useOps.getState().scenario.loading) patchScenario({ loading: false });
  } else if (ev.type === "result") {
    const resp = ev as unknown as ScenarioResponse;
    patchScenario({
      loading: false,
      branch: resp.branch,
      explanation: resp.explanation ?? null,
      steps: resp.steps ?? useOps.getState().scenario.steps,
      impact: resp.impact_diff ?? null,
      deep: resp.deep_supply ?? null,
    });
    if (resp.branch) {
      await refreshBranches();
      await switchBranch(resp.branch);
      toast(`Scenario simulated on branch #${resp.branch}. Map shows the affected graph.`);
    } else {
      toast("The scenario agent produced no branch.", "warn");
    }
  }
}

export function setTime(next: number): void {
  const { time, reports, domain } = useOps.getState();
  const clamped = domain ? Math.min(domain[1], Math.max(domain[0], next)) : next;
  const now = performance.now();
  const arrived = prefersReducedMotion() ? [] : newlyArrived(reports, time, clamped);
  setOps((s) => ({
    time: clamped,
    pulses: [
      ...s.pulses.filter((p) => now - p.at < PULSE_MS),
      ...arrived
        .filter((r) => r.node.lat != null && r.node.lon != null)
        .map((r) => ({ id: r.node.id, lon: r.node.lon as number, lat: r.node.lat as number, at: now })),
    ],
  }));
}

export const PULSE_DURATION_MS = PULSE_MS;
