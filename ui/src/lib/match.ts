// The wargame as the UI sees it: a pure reducer over match SSE events, plus the derived loss series and
// branch tree. No I/O here, so it is unit-tested (match.test.ts).

import type { MatchEvent, MatchSummary, Move, Side } from "../api/types";

export type MatchPhase = "idle" | "starting" | "running" | "paused" | "done" | "stopped" | "error";

export interface MatchView {
  matchId: string | null;
  phase: MatchPhase;
  replay: boolean;
  baseBranch: string | null;
  baseLossPct: number;
  rounds: number;
  model: string | null;
  moves: Move[]; // red, blue and inject moves in play order
  pending: { round: number; side: Side; text?: string } | null;
  error: string | null;
  replayAvailable: boolean;
  summary: MatchSummary | null;
}

export const EMPTY_MATCH: MatchView = {
  matchId: null,
  phase: "idle",
  replay: false,
  baseBranch: null,
  baseLossPct: 0,
  rounds: 0,
  model: null,
  moves: [],
  pending: null,
  error: null,
  replayAvailable: false,
  summary: null,
};

export const isLive = (v: MatchView) => v.phase === "starting" || v.phase === "running" || v.phase === "paused";

export function startMatchView(matchId: string, replay: boolean): MatchView {
  return { ...EMPTY_MATCH, matchId, replay, phase: "starting" };
}

export function reduceMatch(view: MatchView, ev: MatchEvent): MatchView {
  switch (ev.type) {
    case "match_started":
      return {
        ...view,
        phase: "running",
        baseBranch: ev.base_branch,
        baseLossPct: ev.base_loss_pct,
        rounds: ev.rounds,
        model: ev.model ?? null,
        replay: view.replay || Boolean(ev.replay),
      };
    case "move_started":
      return { ...view, pending: { round: ev.round, side: ev.side, text: ev.text } };
    case "move": {
      const { type: _t, replay: _r, ...move } = ev;
      return { ...view, moves: [...view.moves, move], pending: null };
    }
    case "inject":
      return { ...view, moves: [...view.moves, ev.move], pending: null };
    case "status":
      return isLive(view) ? { ...view, phase: ev.state } : view;
    case "error":
      return { ...view, error: ev.message, replayAvailable: Boolean(ev.replay_available), pending: null };
    case "match_done":
      return { ...view, phase: phaseOf(ev.status), summary: ev.summary ?? view.summary, pending: null };
    case "done":
      return isLive(view) ? { ...view, phase: phaseOf(ev.status), pending: null } : view;
    default:
      return view;
  }
}

function phaseOf(status: string): MatchPhase {
  return status === "stopped" ? "stopped" : status === "error" ? "error" : "done";
}

/** Branch the match is on now: the last move's branch, else the base. */
export function headOf(view: MatchView): string | null {
  return view.moves[view.moves.length - 1]?.branch_id ?? view.baseBranch;
}

// ---------------------------------------------------------------- loss-per-round chart

export interface LossPoint {
  x: number; // round position: red at r-0.5, blue at r, an inject after round r at r+0.15
  y: number; // absolute projected loss %
  side: Side;
  move: Move;
}

export function lossSeries(moves: readonly Move[]): LossPoint[] {
  return moves.map((m) => ({
    x: m.side === "red" ? m.round - 0.5 : m.side === "blue" ? m.round : m.round + 0.15,
    y: m.abs_loss_pct,
    side: m.side,
    move: m,
  }));
}

// ---------------------------------------------------------------- branch tree

export interface TreeNode {
  id: string;
  parent: string | null;
  side: Side | "base";
  tag: string; // BASE, R1, B1, EV1 ...
  label: string;
}

export function branchTree(view: MatchView): TreeNode[] {
  if (!view.baseBranch) return [];
  const nodes: TreeNode[] = [
    { id: view.baseBranch, parent: null, side: "base", tag: "BASE", label: view.baseBranch === "main" ? "main" : `#${view.baseBranch}` },
  ];
  let injects = 0;
  for (const m of view.moves) {
    const tag = m.side === "red" ? `R${m.round}` : m.side === "blue" ? `B${m.round}` : `EV${++injects}`;
    nodes.push({ id: m.branch_id, parent: m.parent_id, side: m.side, tag, label: m.label });
  }
  return nodes;
}

/** Plain-language move latency: "LLM 2.1 s · DB 1.8 s". */
export function latencyText(m: Pick<Move, "llm_ms" | "db_ms">): string {
  const s = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
  return `LLM ${s(m.llm_ms)} · DB ${s(m.db_ms)}`;
}

export function signedPct(x: number): string {
  return `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(1)}%`;
}

/** The round an event injected now is applied before (the engine drains injects at round boundaries);
 *  null when it lands after the last round. */
export function injectLandsBefore(view: MatchView): number | null {
  const pending = view.pending && view.pending.side !== "inject" ? view.pending.round : null;
  const played = view.moves.filter((m) => m.side !== "inject").at(-1)?.round ?? 0;
  const next = (pending ?? played) + 1;
  return view.rounds && next > view.rounds ? null : next;
}
