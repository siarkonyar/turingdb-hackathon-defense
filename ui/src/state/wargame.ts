// Wargame actions: start / control / replay a match, follow its SSE stream, and drive the map from it.
// Every API call here returns at once; the match itself runs in the API's background worker.

import { api, eventsUrl } from "../api/client";
import { follow, JOB_EVENTS, MATCH_EVENTS, type Unsubscribe } from "../api/sse";
import type { JobEvent, MatchEvent, Move, RedBlueResult } from "../api/types";
import { headOf, injectLandsBefore, isLive, reduceMatch, startMatchView } from "../lib/match";
import { overlayFromDiff } from "../lib/overlay";
import { message, recordLatency, refreshBranches, runDiff, switchBranch, toast } from "./actions";
import { setOps, useOps, type OneShotState, type WargameState } from "./store";

const FOLLOW_ZOOM = 6.5;
let flySeq = 1_000_000; // distinct from actions.ts's sequence: only the nonce has to change
let unsubscribe: Unsubscribe | null = null;

function patch(p: Partial<WargameState> | ((w: WargameState) => Partial<WargameState>)): void {
  setOps((s) => ({ wargame: { ...s.wargame, ...(typeof p === "function" ? p(s.wargame) : p) } }));
}

function patchOneShot(p: Partial<OneShotState>): void {
  patch((w) => ({ oneShot: { ...w.oneShot, ...p } }));
}

// ---------------------------------------------------------------- panel

export function setWargameOpen(open: boolean): void {
  patch({ open });
  if (open) {
    void refreshAgentStatus();
    void refreshSaved();
  }
}

export async function refreshAgentStatus(): Promise<void> {
  try {
    patch({ status: await api.agentStatus() });
  } catch (err) {
    patch({ status: { available: false, reason: message(err) } });
  }
}

export async function refreshSaved(): Promise<void> {
  try {
    const { matches } = await api.matches();
    const fallback = matches.find((m) => m.file === "demo")?.file ?? matches[0]?.file ?? "";
    patch((w) => ({ saved: matches, replayFile: matches.some((m) => m.file === w.replayFile) ? w.replayFile : fallback }));
  } catch (err) {
    toast(`Could not list saved matches: ${message(err)}`, "warn");
  }
}

export const setWargame = patch;

// ---------------------------------------------------------------- match lifecycle

export async function startMatch(): Promise<void> {
  const { base, rounds } = useOps.getState().wargame;
  try {
    const { match_id } = await api.startMatch(base, rounds);
    subscribe(match_id, false);
  } catch (err) {
    toast(`Could not start the match: ${message(err)}`, "error");
  }
}

export async function startReplay(file?: string): Promise<void> {
  const name = file ?? useOps.getState().wargame.replayFile;
  if (!name) {
    toast("No saved match to replay.", "warn");
    return;
  }
  try {
    const { match_id } = await api.replayMatch(name);
    subscribe(match_id, true);
  } catch (err) {
    toast(`Could not replay ${name}: ${message(err)}`, "error");
  }
}

function subscribe(matchId: string, replay: boolean): void {
  unsubscribe?.();
  patch({ view: startMatchView(matchId, replay), injectNote: null, treePick: null });
  unsubscribe = follow<MatchEvent>(
    eventsUrl("match", matchId),
    MATCH_EVENTS,
    (ev) => void onMatchEvent(matchId, ev),
    (why) => patch((w) => ({ view: { ...w.view, phase: "error", error: why } })),
  );
}

async function onMatchEvent(matchId: string, ev: MatchEvent): Promise<void> {
  if (useOps.getState().wargame.view.matchId !== matchId) return; // a newer match took over
  patch((w) => ({ view: reduceMatch(w.view, ev) }));
  if (ev.type === "match_started" && ev.base_branch !== "main") {
    await refreshBranches();
    if (useOps.getState().wargame.follow) await showBranch(ev.base_branch);
  } else if (ev.type === "move") {
    await showMove(ev);
  } else if (ev.type === "inject") {
    toast(`Event injected: ${ev.text}`, "warn");
    await showMove(ev.move);
  } else if (ev.type === "match_done") {
    toast(ev.status === "done" ? "Match finished." : `Match ${ev.status}.`, ev.status === "done" ? "info" : "warn");
    await Promise.all([refreshBranches(), refreshSaved()]);
  } else if (ev.type === "error") {
    toast(`Match error: ${ev.message}`, "error");
  }
}

/** Map follows the head: load the move's branch overlay, then flash / pulse its targets. */
async function showMove(move: Move): Promise<void> {
  await refreshBranches();
  if (!useOps.getState().wargame.follow) return;
  await showBranch(move.branch_id);
  setOps({ matchFx: { side: move.side, targets: move.targets, arcs: move.arcs, startedAt: performance.now() } });
  const pts = move.targets.filter((t) => Number.isFinite(t.lat) && Number.isFinite(t.lon));
  if (pts.length) {
    const lon = pts.reduce((a, t) => a + t.lon, 0) / pts.length;
    const lat = pts.reduce((a, t) => a + t.lat, 0) / pts.length;
    setOps({ flyTo: { lon, lat, zoom: FOLLOW_ZOOM, nonce: ++flySeq } });
  }
}

/** Switch the map to a branch without the busy pill (moves arrive every few seconds). */
async function showBranch(branchId: string): Promise<void> {
  if (branchId === "main" || useOps.getState().overlays[branchId]) {
    setOps({ activeBranch: branchId, strike: null });
    return;
  }
  try {
    const diff = await api.diff("main", branchId);
    recordLatency(`diff main→${branchId}`, diff);
    setOps((s) => ({ overlays: { ...s.overlays, [branchId]: overlayFromDiff(diff) }, activeBranch: branchId, strike: null }));
  } catch (err) {
    toast(`Could not load branch ${branchId}: ${message(err)}`, "error");
  }
}

export async function controlMatch(action: "pause" | "resume" | "stop"): Promise<void> {
  const { matchId } = useOps.getState().wargame.view;
  if (!matchId) return;
  try {
    await api.controlMatch(matchId, action);
    if (action === "stop") toast("Stopping after the current move.", "info");
  } catch (err) {
    toast(`Could not ${action}: ${message(err)}`, "error");
  }
}

export async function injectEvent(): Promise<void> {
  const { view, injectText } = useOps.getState().wargame;
  const text = injectText.trim();
  if (!view.matchId || !isLive(view) || text.length < 3) return;
  try {
    const { queued } = await api.injectMatch(view.matchId, text);
    const before = injectLandsBefore(useOps.getState().wargame.view);
    patch({ injectNote: `Queued (#${queued}). ${before ? `Applies before round ${before}.` : "Applies after the last round."}` });
  } catch (err) {
    toast(`Inject failed: ${message(err)}`, "error");
  }
}

// ---------------------------------------------------------------- branch tree

/** Click: show that branch (and stop following). Shift-click two nodes: open the Diff view. */
export function pickTreeNode(branchId: string, shift: boolean): void {
  if (!shift) {
    patch({ follow: false, treePick: null });
    void switchBranch(branchId);
    return;
  }
  const first = useOps.getState().wargame.treePick;
  if (first && first !== branchId) {
    patch({ treePick: null });
    void runDiff(first, branchId);
  } else {
    patch({ treePick: branchId });
  }
}

export function setFollow(on: boolean): void {
  patch({ follow: on });
  const head = headOf(useOps.getState().wargame.view);
  if (on && head) void showBranch(head);
}

// ---------------------------------------------------------------- one-shot red vs blue (an agent job)

export async function runOneShot(): Promise<void> {
  patchOneShot({ running: true, steps: [], result: null, error: null });
  try {
    const { job_id } = await api.agentRedBlue();
    follow<JobEvent>(
      eventsUrl("job", job_id),
      JOB_EVENTS,
      (ev) => void onOneShotEvent(ev),
      (why) => patchOneShot({ running: false, error: why }),
    );
  } catch (err) {
    patchOneShot({ running: false, error: message(err) });
  }
}

async function onOneShotEvent(ev: JobEvent): Promise<void> {
  if (ev.type === "step") {
    const { type: _t, ...step } = ev;
    patch((w) => ({ oneShot: { ...w.oneShot, steps: [...w.oneShot.steps, step].slice(-40) } }));
  } else if (ev.type === "result") {
    const result = ev as unknown as RedBlueResult;
    patchOneShot({ running: false, result });
    await refreshBranches();
    if (result.defence_branch) await switchBranch(result.defence_branch);
  } else if (ev.type === "error") {
    patchOneShot({ running: false, error: ev.message });
  } else if (ev.type === "done") {
    patchOneShot({ running: false });
  }
}
