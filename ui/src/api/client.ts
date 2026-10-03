import type {
  AgentStatus,
  BranchesResponse,
  CascadeAskRequest,
  CascadeRequest,
  CascadeResponse,
  JobRef,
  DiffResponse,
  AskResponse,
  ExerciseJob,
  ExercisesResponse,
  MetaResponse,
  NeighboursResponse,
  NodesResponse,
  OriginsResponse,
  ReportsResponse,
  RunStarted,
  ScenarioId,
  SavedMatch,
  SimulateResponse,
  TracksResponse,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function queryString(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter((e): e is [string, string] => e[1] !== undefined && e[1] !== "");
  return entries.length ? `?${new URLSearchParams(entries).toString()}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("API unreachable. Is `uv run uvicorn api.main:app` running?", 0);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    let body: unknown = null;
    try {
      body = await resp.json();
      const d = (body as { detail?: unknown }).detail;
      if (typeof d === "string") detail = d;
    } catch {
      // non-JSON error body: keep the status text
    }
    throw new ApiError(detail || `HTTP ${resp.status}`, resp.status, body);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  resilienceExercises: () => request<ExercisesResponse>("/resilience/exercises"),
  resilienceRun: (scenario_id: ScenarioId) =>
    request<RunStarted>("/resilience/run", { method: "POST", body: JSON.stringify({ scenario_id }) }),
  resilienceAsk: (question: string) =>
    request<AskResponse>("/resilience/ask", { method: "POST", body: JSON.stringify({ question }) }),
  resilienceJob: (jobId: string, after: number) =>
    request<ExerciseJob>(`/resilience/jobs/${encodeURIComponent(jobId)}${queryString({ after: String(after) })}`),
  cascadeOrigins: (q: string, branch = "main") =>
    request<OriginsResponse>(`/cascade/origins${queryString({ q, branch })}`),
  cascade: (req: CascadeRequest) => request<CascadeResponse>("/cascade", { method: "POST", body: JSON.stringify(req) }),
  cascadeAsk: (req: CascadeAskRequest) =>
    request<CascadeResponse>("/cascade/ask", { method: "POST", body: JSON.stringify(req) }),
  meta: () => request<MetaResponse>("/meta"),
  nodes: (types: string[], branch = "main", bbox?: string) =>
    request<NodesResponse>(`/nodes${queryString({ types: types.join(","), branch, bbox })}`),
  neighbours: (id: string, branch = "main") =>
    request<NeighboursResponse>(`/node/${encodeURIComponent(id)}/neighbours${queryString({ branch })}`),
  simulate: (nodeId: string, baseBranch = "main") =>
    request<SimulateResponse>("/simulate", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, base_branch: baseBranch }),
    }),
  discard: (branch: string) => request<void>(`/branches/${encodeURIComponent(branch)}`, { method: "DELETE" }),
  diff: (a: string, b: string) => request<DiffResponse>(`/diff${queryString({ a, b })}`),
  branches: () => request<BranchesResponse>("/branches"),
  reports: (until?: string, branch = "main") =>
    request<ReportsResponse>(`/reports${queryString({ until, branch })}`),
  tracks: (branch = "main") => request<TracksResponse>(`/tracks${queryString({ branch })}`),
  agentStatus: () => request<AgentStatus>("/agent/status"),
  // agent actions are background jobs: POST returns an id, progress streams over SSE (see eventsUrl)
  agentScenario: (question: string, maxSteps = 12) =>
    request<JobRef>("/agent/scenario", { method: "POST", body: JSON.stringify({ question, max_steps: maxSteps }) }),
  agentRedBlue: (threatSteps = 10, defenceSteps = 10) =>
    request<JobRef>("/agent/redblue", {
      method: "POST",
      body: JSON.stringify({ threat_steps: threatSteps, defence_steps: defenceSteps }),
    }),
  startMatch: (baseBranch: string, rounds: number) =>
    request<{ match_id: string }>("/match", { method: "POST", body: JSON.stringify({ base_branch: baseBranch, rounds }) }),
  injectMatch: (matchId: string, text: string) =>
    request<{ queued: number }>(`/match/${encodeURIComponent(matchId)}/inject`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  controlMatch: (matchId: string, action: "pause" | "resume" | "stop") =>
    request<unknown>(`/match/${encodeURIComponent(matchId)}/${action}`, { method: "POST" }),
  replayMatch: (file: string, speed = 1) =>
    request<{ match_id: string }>("/match/replay", { method: "POST", body: JSON.stringify({ file, speed }) }),
  matches: () => request<{ matches: SavedMatch[] }>("/matches"),
};

/** SSE endpoint of a job or match (EventSource cannot send headers; it reconnects with Last-Event-ID). */
export function eventsUrl(kind: "job" | "match", id: string): string {
  const path = kind === "job" ? `/agent/jobs/${encodeURIComponent(id)}` : `/match/${encodeURIComponent(id)}`;
  return `${BASE}${path}/events`;
}

/** Download a persisted match without making another model request. */
export function matchDownloadUrl(file: string, format: "md" | "json"): string {
  return `${BASE}/matches/${encodeURIComponent(file)}/download?format=${format}`;
}
