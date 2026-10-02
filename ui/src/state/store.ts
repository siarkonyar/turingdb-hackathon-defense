// Single app store. State is replaced, never mutated: every update returns new objects/maps.

import { create } from "zustand";

import type {
  Branch,
  DiffResponse,
  Engine,
  GraphNode,
  MetaResponse,
  NeighboursResponse,
  Report,
  SimulateResponse,
  Track,
} from "../api/types";
import { DEFAULT_BASEMAP, type BasemapKind } from "../map/basemap";
import { EMPTY_OVERLAY, type Overlay } from "../lib/overlay";

export type LayerKey = "plant" | "site" | "supplier" | "drone" | "crime" | "cyber" | "report";
export const LAYER_KEYS: LayerKey[] = ["plant", "site", "supplier", "drone", "crime", "cyber", "report"];
export type BaseKind = "plant" | "site" | "supplier" | "drone" | "crime";

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

const EMPTY_BASE: Record<BaseKind, GraphNode[]> = { plant: [], site: [], supplier: [], drone: [], crime: [] };

export const initialState: OpsState = {
  phase: "loading",
  error: null,
  meta: null,
  layers: { plant: true, site: true, supplier: true, drone: true, crime: false, cyber: false, report: true },
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
