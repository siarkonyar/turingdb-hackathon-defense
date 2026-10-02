// Mirrors api/models.py (the contract in docs/api.md). Null fields may be omitted by the server.

export type Kind = "plant" | "site" | "supplier" | "drone" | "crime" | "report" | "part" | "other";
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

export interface ScenarioResponse {
  branch: string | null;
  explanation?: string | null;
  headline?: Record<string, unknown> | null;
  impact_diff?: ImpactDiff | null;
  steps: string[];
  model?: string | null;
}
