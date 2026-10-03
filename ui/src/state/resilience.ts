// Dover recovery chat: a question (typed or a suggestion) starts a run; the job's events become short chat
// messages with buttons that open the right-hand panel: the dependency cascade ("Show the effects") or the
// step-by-step recovery plan ("Show recovery plan"). The map never moves on its own.

import { api } from "../api/client";
import type { AskResponse, ExerciseEvent, ExerciseInfo, RecoveryView } from "../api/types";
import { message, refreshBranches } from "./actions";
import { clearCascade, showCascade } from "./cascade";
import { setOps, useOps, type ChatEntry, type ResilienceState } from "./store";

const POLL_MS = 700;
let runNonce = 0;

function patch(p: Partial<ResilienceState>): void {
  setOps((s) => ({ resilience: { ...s.resilience, ...p } }));
}

function say(entry: ChatEntry): void {
  setOps((s) => ({ resilience: { ...s.resilience, chat: [...s.resilience.chat, entry] } }));
}

export function setResilienceOpen(open: boolean): void {
  patch({ open });
  if (open && !useOps.getState().resilience.exercises.length) void loadExercises();
}

export function setChatQuestion(question: string): void {
  patch({ question });
}

export async function loadExercises(): Promise<void> {
  try {
    const { exercises } = await api.resilienceExercises();
    patch({ exercises });
  } catch (err) {
    say({ kind: "error", text: `The assistant is unavailable: ${message(err)}` });
  }
}

/** Right-hand panel: the disruption's dependency cascade. */
export function showEffects(): void {
  const { disruption } = useOps.getState().resilience;
  if (!disruption) return;
  showCascade(disruption.cascade, { kind: "exercise", title: disruption.title, branch: disruption.branch.branch });
  patch({ side: "effects" });
}

/** Right-hand panel: a recovery plan (this result or an earlier one in the chat), one step at a time. */
export function showRecoveryPlan(view: RecoveryView): void {
  clearCascade();
  patch({ recovery: view, side: "recovery", recoveryStep: 0, stepStartedAt: performance.now() });
}

export function closeSide(): void {
  clearCascade();
  patch({ side: "none" });
}

/** Steps after the starting point: one per action group, then the result. */
export function recoverySteps(view: RecoveryView): number {
  return view.groups.length + 1;
}

export function setRecoveryStep(step: number): void {
  const { recovery } = useOps.getState().resilience;
  if (!recovery) return;
  const next = Math.max(0, Math.min(recoverySteps(recovery), Math.round(step)));
  patch({ recoveryStep: next, stepStartedAt: performance.now() });
}

export const recoveryNext = () => setRecoveryStep(useOps.getState().resilience.recoveryStep + 1);
export const recoveryPrev = () => setRecoveryStep(useOps.getState().resilience.recoveryStep - 1);

function handle(e: ExerciseEvent): void {
  switch (e.type) {
    case "disruption":
      patch({ disruption: e.data });
      say({ kind: "disruption", view: e.data });
      void refreshBranches();
      break;
    case "phase":
      if (e.data.phase === "recovery") say({ kind: "assistant", text: "Working out a recovery plan…" });
      break;
    case "agent_step":
      patch({ progress: e.data });
      break;
    case "recovery":
      patch({ recovery: e.data, progress: null });
      say({ kind: "recovery", view: e.data });
      void refreshBranches();
      break;
    case "error":
      say({ kind: "error", text: e.data.message });
      break;
    default:
      break;
  }
}

async function follow(jobId: string, nonce: number): Promise<void> {
  let after = 0;
  for (;;) {
    if (nonce !== runNonce) return; // a newer run took over
    const job = await api.resilienceJob(jobId, after);
    job.events.forEach(handle);
    after = job.next;
    if (job.status !== "running") return;
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}

async function start(text: string, request: () => Promise<AskResponse>): Promise<void> {
  if (useOps.getState().resilience.running || !text.trim()) return;
  runNonce += 1;
  const nonce = runNonce;
  closeSide();
  patch({ running: "pending", question: "", progress: null });
  say({ kind: "user", text });
  try {
    const answer = await request();
    if (!answer.job_id) {
      say({ kind: "assistant", text: answer.reply ?? "I could not interpret that." });
      return;
    }
    patch({ running: answer.scenario_id ?? "pending", disruption: null, recovery: null });
    say({ kind: "assistant",
      text: `Understood: ${answer.title}, ${answer.hours} hours. Running the dependency query on TuringDB…` });
    await follow(answer.job_id, nonce);
  } catch (err) {
    say({ kind: "error", text: message(err) });
  } finally {
    if (nonce === runNonce) patch({ running: null, progress: null });
  }
}

/** Free text: the server ties it to an event in the corridor graph, or answers in plain words. */
export function askAssistant(): Promise<void> {
  const text = useOps.getState().resilience.question.trim();
  return start(text, () => api.resilienceAsk(text));
}

/** A suggestion: exactly the same path as typing it. */
export function askSuggestion(ex: ExerciseInfo): Promise<void> {
  return start(ex.prompt, () => api.resilienceAsk(ex.prompt));
}

export function clearChat(): void {
  if (useOps.getState().resilience.running) return;
  closeSide();
  patch({ chat: [], disruption: null, recovery: null, progress: null });
}
