// Impact cascade actions. The map layer and <CascadeStepper /> both read `s.cascade`, so a cascade shown
// from the Impact panel or from a vulnerability branch (Plan B) behaves identically.

import { ApiError, api } from "../api/client";
import type { CascadeResponse, OriginCandidate } from "../api/types";
import { clampStep } from "../lib/cascade";
import { message, recordLatency, toast } from "./actions";
import { setOps, useOps, type CascadeSource, type CascadeState } from "./store";

function patch(p: Partial<CascadeState>): void {
  setOps((s) => ({ cascade: { ...s.cascade, ...p } }));
}

function setStep(step: number): void {
  const { result } = useOps.getState().cascade;
  if (!result) return;
  const next = clampStep(step, result);
  patch({ step: next, stepStartedAt: performance.now() }); // the map stays where the operator is looking
}

export function setCascadeOpen(open: boolean): void {
  patch({ open });
}

export function setCascadeQuestion(question: string): void {
  patch({ question });
}

export function showCascade(result: CascadeResponse, source: CascadeSource): void {
  patch({ result, source, step: 0, stepStartedAt: performance.now(), error: null, loading: false, candidates: [] });
  recordLatency(`cascade ${result.origin.name}`, result);
}

export const cascadeNext = () => setStep(useOps.getState().cascade.step + 1);
export const cascadePrev = () => setStep(useOps.getState().cascade.step - 1);
export const cascadeGoTo = (step: number) => setStep(step);
export const cascadeReset = () => setStep(0);
export function cascadeShowAll(): void {
  const { result } = useOps.getState().cascade;
  if (result) setStep(result.max_degree);
}

export function clearCascade(): void {
  patch({ result: null, source: null, step: 0, candidates: [], error: null });
}

function candidatesOf(err: unknown): OriginCandidate[] {
  if (!(err instanceof ApiError) || err.status !== 422) return [];
  const body = err.body as { candidates?: OriginCandidate[] } | null;
  return Array.isArray(body?.candidates) ? body.candidates : [];
}

export async function askCascade(): Promise<void> {
  const { question } = useOps.getState().cascade;
  patch({ loading: true, error: null, candidates: [] });
  try {
    const result = await api.cascadeAsk({ question, branch: "main" });
    showCascade(result, { kind: "query", title: question, branch: result.branch });
  } catch (err) {
    patch({ loading: false, error: message(err), candidates: candidatesOf(err) });
  }
}

export async function runCascadeFor(originId: string, title: string): Promise<void> {
  patch({ open: true, loading: true, error: null, candidates: [] });
  setOps({ contextMenu: null });
  try {
    const result = await api.cascade({ origin_id: originId, branch: "main" });
    showCascade(result, { kind: "query", title, branch: result.branch });
  } catch (err) {
    patch({ loading: false, error: message(err) });
    toast(`Cascade failed: ${message(err)}`, "error");
  }
}
