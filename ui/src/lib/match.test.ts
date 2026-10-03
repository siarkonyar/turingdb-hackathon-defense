import { describe, expect, it } from "vitest";

import type { MatchEvent, Move, Side } from "../api/types";
import { EMPTY_MATCH, branchTree, headOf, injectLandsBefore, isLive, latencyText, lossSeries, reduceMatch, signedPct, startMatchView } from "./match";

const move = (side: Side, round: number, branch: string, parent: string, abs: number): Move => ({
  round,
  side,
  action: side === "red" ? "strike_supplier" : side === "blue" ? "backup_all_affected_parts" : "wipe_bbox",
  args: {},
  actions: [],
  branch_id: branch,
  parent_id: parent,
  label: `${side} ${round}`,
  rationale: "because",
  loss_pct: abs - 20,
  abs_loss_pct: abs,
  llm_ms: 2100,
  db_ms: 850,
  latency_ms: 2950,
  targets: [],
  arcs: [],
  fallback: false,
});

const play = (events: MatchEvent[]) => events.reduce(reduceMatch, startMatchView("m1", false));

const started: MatchEvent = { type: "match_started", base_branch: "25", rounds: 2, base_loss_pct: 20, model: "qwen" };

describe("reduceMatch", () => {
  it("follows a match from start to finish", () => {
    const v = play([
      { type: "job_started", job_id: "m1" },
      started,
      { type: "move_started", round: 1, side: "red", head: "25" },
      { type: "move", ...move("red", 1, "30", "25", 31) },
      { type: "move_started", round: 1, side: "blue", head: "30" },
      { type: "move", ...move("blue", 1, "31", "30", 24) },
      { type: "round_done", round: 1, head: "31", loss_pct: 4, abs_loss_pct: 24 },
      { type: "match_done", status: "done", summary: { status: "done", final_loss_pct: 4 } },
      { type: "done", status: "done" },
    ]);
    expect(v.phase).toBe("done");
    expect(v.baseBranch).toBe("25");
    expect(v.baseLossPct).toBe(20);
    expect(v.moves.map((m) => m.side)).toEqual(["red", "blue"]);
    expect(v.pending).toBeNull();
    expect(headOf(v)).toBe("31");
    expect(v.summary?.final_loss_pct).toBe(4);
    expect(isLive(v)).toBe(false);
  });

  it("shows the side that is thinking", () => {
    const v = play([started, { type: "move_started", round: 1, side: "red", head: "25" }]);
    expect(v.pending).toEqual({ round: 1, side: "red", text: undefined });
    expect(headOf(v)).toBe("25");
  });

  it("puts injected events in the feed in play order", () => {
    const v = play([
      started,
      { type: "move", ...move("red", 1, "30", "25", 31) },
      { type: "move", ...move("blue", 1, "31", "30", 24) },
      { type: "move_started", round: 1, side: "inject", head: "31", text: "port closed" },
      { type: "inject", text: "port closed", branch: "32", move: move("inject", 1, "32", "31", 40) },
      { type: "move", ...move("red", 2, "33", "32", 45) },
    ]);
    expect(v.moves.map((m) => `${m.side}:${m.parent_id}`)).toEqual(["red:25", "blue:30", "inject:31", "red:32"]);
  });

  it("tracks pause and resume only while live", () => {
    let v = play([started, { type: "status", state: "paused" }]);
    expect(v.phase).toBe("paused");
    v = reduceMatch(v, { type: "status", state: "running" });
    expect(v.phase).toBe("running");
    v = reduceMatch(v, { type: "match_done", status: "stopped" });
    expect(reduceMatch(v, { type: "status", state: "running" }).phase).toBe("stopped");
  });

  it("surfaces an LLM outage with the replay hint", () => {
    const v = play([
      { type: "error", message: "LLM unavailable: no key", replay_available: true },
      { type: "done", status: "error" },
    ]);
    expect(v.phase).toBe("error");
    expect(v.error).toContain("no key");
    expect(v.replayAvailable).toBe(true);
  });

  it("does not let a trailing done overwrite the match result", () => {
    const v = play([started, { type: "match_done", status: "stopped" }, { type: "done", status: "done" }]);
    expect(v.phase).toBe("stopped");
  });

  it("marks replays", () => {
    const v = [{ ...started, replay: true } as MatchEvent].reduce(reduceMatch, startMatchView("r1", true));
    expect(v.replay).toBe(true);
    expect(EMPTY_MATCH.replay).toBe(false);
  });
});

describe("derived views", () => {
  const moves = [move("red", 1, "30", "25", 31), move("blue", 1, "31", "30", 24), move("inject", 1, "32", "31", 40), move("red", 2, "33", "32", 45)];

  it("places red mid-round, blue at the round end and injects between rounds", () => {
    expect(lossSeries(moves).map((p) => [p.side, p.x, p.y])).toEqual([
      ["red", 0.5, 31],
      ["blue", 1, 24],
      ["inject", 1.15, 40],
      ["red", 1.5, 45],
    ]);
  });

  it("builds the branch tree from the base through every move", () => {
    const view = { ...EMPTY_MATCH, baseBranch: "25", moves };
    expect(branchTree(view).map((n) => `${n.tag}:${n.id}<${n.parent ?? "-"}`)).toEqual([
      "BASE:25<-",
      "R1:30<25",
      "B1:31<30",
      "EV1:32<31",
      "R2:33<32",
    ]);
    expect(branchTree(EMPTY_MATCH)).toEqual([]);
  });

  it("formats latency and signed loss", () => {
    expect(latencyText({ llm_ms: 2100, db_ms: 850 })).toBe("LLM 2.1 s · DB 850 ms");
    expect(signedPct(3.74)).toBe("+3.7%");
    expect(signedPct(-2)).toBe("−2.0%");
    expect(signedPct(0)).toBe("±0.0%");
  });
});

describe("injectLandsBefore", () => {
  const base = { ...EMPTY_MATCH, phase: "running" as const, rounds: 3 };
  it("lands after the round in progress, matching the engine's round boundaries", () => {
    expect(injectLandsBefore(base)).toBe(1); // nothing played yet
    expect(injectLandsBefore({ ...base, pending: { round: 1, side: "red" } })).toBe(2); // red thinking in R1
    expect(injectLandsBefore({ ...base, moves: [move("red", 1, "30", "25", 31)], pending: { round: 1, side: "blue" } })).toBe(2);
    expect(injectLandsBefore({ ...base, moves: [move("red", 1, "30", "25", 31), move("blue", 1, "31", "30", 24)] })).toBe(2);
    expect(injectLandsBefore({ ...base, pending: { round: 3, side: "red" } })).toBeNull(); // after the last round
  });
});
