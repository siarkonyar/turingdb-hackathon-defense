// Mirrors api/models.py (the contract in docs/api.md). Null fields may be omitted by the server.

export type Kind =
  | "plant"
  | "site"
  | "supplier"
  | "drone"
  | "crime"
  | "report"
  | "part"
  | "facility"
  | "port"
  | "other";
export type Status = "at_risk" | "lost" | "no_power";
export type BranchKind = "main" | "hypothesis" | "strike" | "change" | "threat" | "defence" | "scenario";
export type Engine = "turingdb" | "fixtures";

export interface GraphNode {
  id: string;
  kind: Kind;
  label: string;
  name: string;
  lat?: number | null;
  lon?: number | null;
  source?: string | null;
  timestamp?: string | null;
  synthetic?: boolean | null;
  status?: Status | null;
  importance: number;
  fuel?: string | null;
  capacity_mw?: number | null;
  exposure?: number | null;
  confidence?: number | null;
}

export interface QueryTrace {
  cypher: string;
  ms: number | null;
}

export interface Timed {
  engine: Engine;
  latency_ms: number;
  roundtrip_ms: number;
  queries?: QueryTrace[];
}

export interface NodesResponse extends Timed {
  branch: string;
  nodes: GraphNode[];
}

export interface NeighbourGroup {
  rel: string;
  direction: "out" | "in";
  total: number;
  nodes: GraphNode[];
}

export interface NeighboursResponse extends Timed {
  branch: string;
  node: GraphNode;
  properties: Record<string, unknown>;
  groups: NeighbourGroup[];
}

export interface Affected {
  node: GraphNode;
  hop: number;
  via: string;
  parent_id: string;
}

export interface Arc {
  source: [number, number];
  target: [number, number];
  source_id: string;
  target_id: string;
  hop: number;
  rel: string;
}

export interface Kpis {
  assets_at_risk: number;
  sites_without_power: number;
  suppliers_without_power: number;
  parts_affected: number;
}

export interface SimulateResponse extends Timed {
  branch: string;
  base_branch: string;
  struck: GraphNode;
  affected: Affected[];
  lost: GraphNode[];
  arcs: Arc[];
  kpis: Kpis;
}

export interface Commit {
  hash: string;
  index: number;
  node_delta: number;
  edge_delta: number;
  time?: string | null;
}

export interface Branch {
  id: string;
  kind: BranchKind;
  label: string;
  description?: string | null;
  confidence?: number | null;
  commits?: Commit[];
}

export interface BranchesResponse extends Timed {
  branches: Branch[];
}

export interface Change {
  node: GraphNode;
  fields: Record<string, [unknown, unknown]>;
}

export interface DiffResponse extends Timed {
  a: string;
  b: string;
  added: GraphNode[];
  removed: GraphNode[];
  changed: Change[];
}

export interface Report {
  node: GraphNode;
  report_id: string;
  text: string;
  claim?: string | null;
  source_type?: string | null;
  mentions: string[];
  contradicts?: string | null;
}

export interface ReportsResponse extends Timed {
  branch: string;
  until: string | null;
  reports: Report[];
}

export interface Track {
  id: string;
  name: string;
  path: [number, number][];
  timestamps: number[];
}

export interface TracksResponse extends Timed {
  branch: string;
  tracks: Track[];
}

export interface MetaResponse {
  engine: Engine;
  graph: string;
  layers: string[];
}

export interface ImpactDiff {
  a: string;
  b: string;
  loss_a_pct: number;
  loss_b_pct: number;
  loss_delta_pct: number;
  per_site: Record<string, { a: number; b: number }>;
  sites_down_a: string[];
  sites_down_b: string[];
  critical_parts_a: number;
  critical_parts_b: number;
}

export interface AgentStatus {
  available: boolean;
  model?: string;
  graph?: string;
  reason?: string;
}

export interface DeepSupply {
  facilities_destroyed: number;
  facilities_flagged: number;
  facilities_downstream: number;
  platforms_built_at_hit_facility: string[];
  platforms_downstream_count: number;
}

export interface ScenarioResponse {
  branch: string | null;
  explanation?: string | null;
  headline?: Record<string, unknown> | null;
  impact_diff?: ImpactDiff | null;
  deep_supply?: DeepSupply | null;
  steps: string[];
  model?: string | null;
}

// ---------------------------------------------------------------- agent jobs + the wargame (docs/api.md)

export interface JobRef {
  job_id: string;
}

export interface JobStep {
  agent: string;
  action: string;
  thought: string;
  args: Record<string, unknown>;
  observation: string;
}

export type Side = "red" | "blue" | "inject";

export interface MoveTarget {
  id: string;
  name: string;
  kind: Kind;
  lat: number;
  lon: number;
  status?: Status | null;
}

export interface Move {
  round: number;
  side: Side;
  action: string;
  args: Record<string, unknown>;
  actions: { action: string; args: Record<string, unknown> }[];
  branch_id: string;
  parent_id: string;
  label: string;
  rationale: string;
  loss_pct: number; // additional loss vs the base, percentage points
  abs_loss_pct: number;
  llm_ms: number;
  db_ms: number;
  latency_ms: number;
  targets: MoveTarget[];
  arcs: Arc[];
  fallback: boolean;
  breakdown?: { deep_pct?: number | null; legacy_pct?: number | null }; // absolute loss per layer
}

export interface MatchSummary {
  match_id?: string;
  status: string;
  base_branch?: string;
  head?: string;
  rounds_played?: number;
  base_loss_pct?: number;
  final_loss_pct?: number;
  llm_ms?: number;
  db_ms?: number;
  file?: string;
}

export interface SavedMatch {
  file: string;
  id: string;
  created: string | null;
  base_branch: string;
  rounds: number;
  status: string;
  moves: number;
  final_loss_pct: number | null;
  model: string | null;
}

/** One SSE event from /match/{id}/events (`type` is the SSE event name). */
export type MatchEvent =
  | { type: "job_started"; job_id: string }
  | { type: "match_started"; match_id?: string; base_branch: string; rounds: number; base_loss_pct: number; model?: string | null; replay?: boolean }
  | { type: "move_started"; round: number; side: Side; head: string; text?: string }
  | ({ type: "move"; replay?: boolean } & Move)
  | { type: "inject"; text: string; branch: string; move: Move }
  | { type: "round_done"; round: number; head: string; loss_pct: number; abs_loss_pct: number }
  | { type: "status"; state: "paused" | "running" }
  | { type: "match_done"; status: string; summary?: MatchSummary }
  | { type: "error"; message: string; replay_available?: boolean }
  | { type: "done"; status: string };

export interface RedBlueResult {
  headline?: string;
  baseline_pct?: number;
  threat_branch?: string;
  threat_loss_pct?: number;
  defence_branch?: string;
  defence_loss_pct?: number;
}

/** One SSE event from /agent/jobs/{id}/events. */
export type JobEvent =
  | { type: "job_started"; job_id: string; kind: string }
  | ({ type: "step" } & JobStep)
  | ({ type: "result" } & Record<string, unknown>)
  | { type: "error"; message: string }
  | { type: "done"; status: string };
