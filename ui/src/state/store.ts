// Single app store. State is replaced, never mutated: every update returns new objects/maps.

import { create } from "zustand";

import type {
  AgentStatus,
  Arc,
  Branch,
  DeepSupply,
  DiffResponse,
  Engine,
  GraphNode,
  ImpactDiff,
  JobStep,
  MetaResponse,
  MoveTarget,
  NeighboursResponse,
  RedBlueResult,
  Report,
  SavedMatch,
  Side,
  SimulateResponse,
  Track,
} from "../api/types";
import { EMPTY_MATCH, type MatchView } from "../lib/match";
import { DEFAULT_BASEMAP, type BasemapKind } from "../map/basemap";
import { EMPTY_OVERLAY, type Overlay } from "../lib/overlay";

export type LayerKey = "plant" | "site" | "supplier" | "facility" | "port" | "drone" | "crime" | "cyber" | "report";
export const LAYER_KEYS: LayerKey[] = ["plant", "site", "supplier", "facility", "port", "drone", "crime", "cyber", "report"];
export type BaseKind = "plant" | "site" | "supplier" | "facility" | "port" | "drone" | "crime";

export interface LatencyStat {
  op: string;
  ms: number;
  roundtripMs: number;
  engine: Engine;
  queries: number;
}

export interface StrikeAnim {
  sim: SimulateResponse;
  startedAt: number; // performance.now()
}

export interface Pulse {
  id: string;
  lon: number;
  lat: number;
  at: number; // performance.now()
}

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "warn" | "error";
}

export interface FlyTarget {
  lon: number;
  lat: number;
  zoom?: number;
  nonce: number;
}

export interface Drawer {
  nodeId: string;
  loading: boolean;
  data: NeighboursResponse | null;
  error: string | null;
  note: string | null;
}

export interface DiffState {
  a: string;
  b: string;
  result: DiffResponse | null;
  loading: boolean;
}

export interface ScenarioState {
  open: boolean;
  question: string;
  loading: boolean;
  error: string | null;
  branch: string | null;
  explanation: string | null;
  steps: string[];
  thought: string | null; // the agent's latest reasoning, streamed live
  impact: ImpactDiff | null;
  deep: DeepSupply | null;
  status: AgentStatus | null;
}

export interface OneShotState {
  running: boolean;
  steps: JobStep[];
  result: RedBlueResult | null;
  error: string | null;
}

export interface WargameState {
  open: boolean;
  status: AgentStatus | null; // LLM availability (GET /agent/status)
  base: string;
  rounds: number;
  view: MatchView;
  follow: boolean; // the map follows the match head
  saved: SavedMatch[];
  replayFile: string;
  injectText: string;
  injectNote: string | null;
  treePick: string | null; // first node of a shift-click diff pair
  oneShot: OneShotState;
}

/** A move's map choreography: red flashes + cascade arcs, blue pulses, amber for injected events. */
export interface MatchFx {
  side: Side;
  targets: MoveTarget[];
  arcs: Arc[];
  startedAt: number; // performance.now()
}

export interface OpsState {
  phase: "loading" | "ready" | "error";
  error: string | null;
  meta: MetaResponse | null;
  layers: Record<LayerKey, boolean>;
  basemap: BasemapKind;
  basemapFallback: boolean; // the chosen basemap failed; built-in outlines are showing
  base: Record<BaseKind, GraphNode[]>;
  nodeIndex: ReadonlyMap<string, GraphNode>;
  reports: Report[];
  tracks: Track[];
  branches: Branch[];
  activeBranch: string;
  overlays: Readonly<Record<string, Overlay>>;
  diff: DiffState | null;
  diffOpen: boolean;
  scenario: ScenarioState;
  wargame: WargameState;
  matchFx: MatchFx | null;
  branchMenuOpen: boolean;
  drawer: Drawer | null;
  contextMenu: { x: number; y: number; node: GraphNode } | null;
  hover: { x: number; y: number; node: GraphNode } | null;
  domain: [number, number] | null;
  time: number;
  playing: boolean;
  strike: StrikeAnim | null;
  pulses: Pulse[];
  latency: LatencyStat | null;
  busy: string | null;
  toasts: Toast[];
  flyTo: FlyTarget | null;
}

const EMPTY_BASE: Record<BaseKind, GraphNode[]> = {
  plant: [],
  site: [],
  supplier: [],
  facility: [],
  port: [],
  drone: [],
  crime: [],
};

export const initialState: OpsState = {
  phase: "loading",
  error: null,
  meta: null,
  layers: {
    plant: true,
    site: true,
    supplier: true,
    facility: true,
    port: true,
    drone: true,
    crime: false,
    cyber: false,
    report: true,
  },
  basemap: DEFAULT_BASEMAP,
  basemapFallback: false,
  base: EMPTY_BASE,
  nodeIndex: new Map(),
  reports: [],
  tracks: [],
  branches: [],
  activeBranch: "main",
  overlays: { main: EMPTY_OVERLAY },
  diff: null,
  diffOpen: false,
  scenario: {
    open: false,
    question: "A catastrophic event has destroyed everything across Manchester. How would this affect the rest of the city and its connected infrastructure?",
    loading: false,
    error: null,
    branch: null,
    explanation: null,
    steps: [],
    thought: null,
    impact: null,
    deep: null,
    status: null,
  },
  wargame: {
    open: false,
    status: null,
    base: "main",
    rounds: 3,
    view: EMPTY_MATCH,
    follow: true,
    saved: [],
    replayFile: "",
    injectText: "the Liverpool port is closed",
    injectNote: null,
    treePick: null,
    oneShot: { running: false, steps: [], result: null, error: null },
  },
  matchFx: null,
  branchMenuOpen: false,
  drawer: null,
  contextMenu: null,
  hover: null,
  domain: null,
  time: 0,
  playing: false,
  strike: null,
  pulses: [],
  latency: null,
  busy: null,
  toasts: [],
  flyTo: null,
};

export const useOps = create<OpsState>()(() => initialState);

export const setOps = (patch: Partial<OpsState> | ((s: OpsState) => Partial<OpsState>)) =>
  useOps.setState(patch as Partial<OpsState>);

export function activeOverlay(s: OpsState): Overlay {
  return s.overlays[s.activeBranch] ?? EMPTY_OVERLAY;
}

export function activeBranchInfo(s: OpsState): Branch | undefined {
  return s.branches.find((b) => b.id === s.activeBranch);
}
