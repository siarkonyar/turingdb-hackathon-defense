import type {
  BranchesResponse,
  DiffResponse,
  MetaResponse,
  NeighboursResponse,
  NodesResponse,
  ReportsResponse,
  SimulateResponse,
  TracksResponse,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
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
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body: keep the status text
    }
    throw new ApiError(detail || `HTTP ${resp.status}`, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
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
};
