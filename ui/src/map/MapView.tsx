import "maplibre-gl/dist/maplibre-gl.css";

import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { Map as MlMap, setWorkerUrl, type MapMouseEvent } from "maplibre-gl";
// MapLibre 6 loads its worker from next to its own module, which Vite breaks: the build ships a
// bundled worker, dev serves the raw worker module (plugin in vite.config.ts).
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useMemo, useRef, useState } from "react";

import type { GraphNode, SimulateResponse } from "../api/types";
import { arcTrips, arrivalTimes } from "../lib/arcs";
import { useReducedMotion } from "../lib/motion";
import { diffClasses, type Overlay } from "../lib/overlay";
import { isoToEpoch } from "../lib/time";
import { PULSE_DURATION_MS, selectNode, toast } from "../state/actions";
import { activeOverlay, setOps, useOps } from "../state/store";
import { FALLBACK_STYLE, loadBasemap, outlineStyle } from "./basemap";
import { buildIconAtlas } from "./iconAtlas";
import { buildDroneLayers, buildPulseLayer, buildStaticLayers, buildStrikeLayers, pickedNode } from "./layers";
import { buildCascadeLayers, cascadeAnimating } from "./cascadeLayers";
import { buildRecoveryLayers, recoveryAnimating } from "./resilienceLayers";
import { buildMatchFxLayers, matchFxActive } from "./matchLayers";

setWorkerUrl(import.meta.env.PROD ? maplibreWorkerUrl : "/vendor/maplibre/maplibre-gl-worker.mjs");

const INITIAL_VIEW = import.meta.env.VITE_OPSMAP_PROFILE === "dover"
  ? { center: [1.52, 51.02] as [number, number], zoom: 6.1 }
  : { center: [7.5, 50.2] as [number, number], zoom: 4.15 };
const ZOOM_STEP = 4; // re-filter plants every quarter zoom level
const FLY_DEFAULT_ZOOM = 8.5;
const DRAWER_PAD = 420;
const SHOCKWAVE_TAIL_MS = 1400;

function withoutStrike(overlay: Overlay, sim: SimulateResponse): Overlay {
  const ids = new Set([sim.struck.id, ...sim.affected.map((a) => a.node.id)]);
  return { entries: new Map([...overlay.entries].filter(([id]) => !ids.has(id))), added: overlay.added };
}

export function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const deckRef = useRef<MapboxOverlay | null>(null);
  const staticRef = useRef<{ layers: Layer[]; version: number }>({ layers: [], version: 0 });
  const [zoom, setZoom] = useState(INITIAL_VIEW.zoom);
  const reduced = useReducedMotion();
  const atlas = useMemo(buildIconAtlas, []);

  const base = useOps((s) => s.base);
  const layers = useOps((s) => s.layers);
  const overlay = useOps(activeOverlay);
  const overlayKey = useOps((s) => `${s.activeBranch}:${activeOverlay(s).entries.size}`);
  const strike = useOps((s) => s.strike);
  const diffResult = useOps((s) => (s.diffOpen ? (s.diff?.result ?? null) : null));
  const selectedId = useOps((s) => s.drawer?.nodeId ?? null);
  const reports = useOps((s) => s.reports);
  const nodeIndex = useOps((s) => s.nodeIndex);
  const basemap = useOps((s) => s.basemap);
  const flyTo = useOps((s) => s.flyTo);
  const visibleReportCount = useOps(
    (s) => s.reports.filter((r) => (isoToEpoch(r.node.timestamp) ?? Infinity) <= s.time).length,
  );

  // ---------------------------------------------------------------- strike choreography
  const strikePlan = useMemo(() => {
    if (!strike) return null;
    const { trips, durationMs } = arcTrips(strike.sim.arcs, reduced);
    const targets = strike.sim.affected.map((a) => a.node).filter((n) => n.lat != null && n.lon != null);
    return { trips, durationMs, arrivals: arrivalTimes(trips), targets };
  }, [strike, reduced]);
  const [settledStrike, setSettledStrike] = useState<SimulateResponse | null>(null);
  useEffect(() => {
    if (!strike || !strikePlan) return;
    const left = strikePlan.durationMs - (performance.now() - strike.startedAt);
    const timer = window.setTimeout(() => setSettledStrike(strike.sim), Math.max(0, left));
    return () => window.clearTimeout(timer);
  }, [strike, strikePlan]);
  const shownOverlay =
    strike && settledStrike !== strike.sim ? withoutStrike(overlay, strike.sim) : overlay;

  // ---------------------------------------------------------------- static layers
  const facilities = useMemo(() => [...base.site, ...base.supplier, ...base.facility, ...base.port], [base]);
  const visibleReports = useMemo(
    () =>
      [...reports]
        .sort((a, b) => (isoToEpoch(a.node.timestamp) ?? 0) - (isoToEpoch(b.node.timestamp) ?? 0))
        .slice(0, visibleReportCount),
    [reports, visibleReportCount],
  );
  const diffMap = useMemo(() => (diffResult ? diffClasses(diffResult) : null), [diffResult]);
  const settledKey = `${overlayKey}:${shownOverlay.entries.size}`;

  useEffect(() => {
    staticRef.current = {
      layers: buildStaticLayers({
        plants: base.plant,
        facilities,
        sites: base.site,
        crimes: base.crime,
        chokepoints: base.chokepoint,
        reports: visibleReports,
        overlay: shownOverlay,
        overlayKey: settledKey,
        layers,
        zoom,
        atlas,
        selectedId,
        diff: diffMap,
        nodeIndex,
      }),
      version: staticRef.current.version + 1,
    };
    // shownOverlay is derived from overlay/strike/settledStrike, all captured by settledKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, facilities, visibleReports, settledKey, layers, zoom, atlas, selectedId, diffMap, nodeIndex]);

  // ---------------------------------------------------------------- drones (float32-safe times)
  const tracks = useOps((s) => s.tracks);
  const origin = useOps((s) => s.domain?.[0] ?? 0);
  const relTimestamps = useMemo(() => tracks.map((t) => t.timestamps.map((x) => x - origin)), [tracks, origin]);

  // ---------------------------------------------------------------- render loop
  useEffect(() => {
    let raf = 0;
    let lastKey = "";
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const deck = deckRef.current;
      if (!deck) return;
      const s = useOps.getState();
      const now = performance.now();
      const elapsed = strike ? now - strike.startedAt : 0;
      const strikeMoving = Boolean(strikePlan) && elapsed < (strikePlan?.durationMs ?? 0) + SHOCKWAVE_TAIL_MS;
      const pulsing = s.pulses.some((p) => now - p.at < PULSE_DURATION_MS);
      const fxMoving = matchFxActive(s.matchFx, now);
      const cas = s.cascade;
      const res = s.resilience;
      const rec = res.side === "recovery" ? res.recovery : null;
      const recMoving = Boolean(rec) && !reduced && recoveryAnimating(res.stepStartedAt, now);
      const casActive = Boolean(cas.result) && !rec;
      const casMoving = casActive && (!reduced || cascadeAnimating(cas, now));
      const key = [staticRef.current.version, s.time, strikeMoving ? now : "still", pulsing ? now : "", fxMoving ? now : "",
        s.layers.drone, casActive ? `${cas.step}|${casMoving ? now : "still"}` : "",
        rec ? `rec|${res.recoveryStep}|${res.stepStartedAt}|${recMoving ? now : "still"}` : ""].join("|");
      if (key === lastKey) return;
      lastKey = key;

      const out: Layer[] = [...staticRef.current.layers];
      if (s.layers.drone && tracks.length) {
        out.push(
          ...buildDroneLayers({ tracks, origin, relTimestamps, time: s.time, overlay: activeOverlay(s), atlas, nodeIndex: s.nodeIndex }),
        );
      }
      if (strike && strikePlan) {
        out.push(
          ...buildStrikeLayers({
            trips: strikePlan.trips,
            elapsedMs: strikeMoving ? elapsed : Number.MAX_SAFE_INTEGER,
            struck: strike.sim.struck,
            arrivals: strikePlan.arrivals,
            targets: strikePlan.targets,
            reducedMotion: reduced,
          }),
        );
      }
      const pulse = buildPulseLayer(s.pulses, now, PULSE_DURATION_MS);
      if (pulse) out.push(pulse);
      if (fxMoving && s.matchFx) out.push(...buildMatchFxLayers(s.matchFx, now, reduced));
      if (casActive && cas.result) {
        out.push(...buildCascadeLayers({ result: cas.result, step: cas.step, elapsedMs: now - cas.stepStartedAt, now, reducedMotion: reduced }));
      }
      if (rec) {
        out.push(...buildRecoveryLayers({ view: rec, step: res.recoveryStep, elapsedMs: now - res.stepStartedAt, reducedMotion: reduced }));
      }
      deck.setProps({ layers: out });
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [strike, strikePlan, tracks, origin, relTimestamps, atlas, reduced]);

  // ---------------------------------------------------------------- map + overlay lifecycle
  useEffect(() => {
    if (!container.current) return;
    const map = new MlMap({
      container: container.current,
      style: FALLBACK_STYLE,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
      minZoom: 1.5,
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      renderWorldCopies: false,
      attributionControl: { compact: true },
    });
    map.touchZoomRotate.disableRotation();
    const deck = new MapboxOverlay({
      interleaved: false,
      layers: [],
      pickingRadius: 6,
      onClick: (info: PickingInfo) => {
        const node = pickedNode(info);
        setOps({ contextMenu: null });
        if (node) void selectNode(node);
      },
      onHover: (info: PickingInfo) => {
        const node = pickedNode(info);
        map.getCanvas().style.cursor = node ? "pointer" : "";
        setOps({ hover: node ? { x: info.x, y: info.y, node } : null });
      },
    });
    map.addControl(deck);
    map.on("zoom", () => setZoom(Math.round(map.getZoom() * ZOOM_STEP) / ZOOM_STEP));
    map.on("contextmenu", (e: MapMouseEvent) => {
      e.preventDefault();
      const info = deck.pickObject({ x: e.point.x, y: e.point.y, radius: 8 });
      const node: GraphNode | null = info ? pickedNode(info) : null;
      setOps({ contextMenu: node ? { x: e.point.x, y: e.point.y, node } : null, hover: null });
    });
    map.on("movestart", () => setOps({ contextMenu: null }));
    mapRef.current = map;
    deckRef.current = deck;
    if (import.meta.env.DEV) Object.assign(window, { __opsmap: { map, deck } }); // debugging + screenshot script
    return () => {
      deckRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let cancelled = false;
    loadBasemap(basemap)
      .then((style) => {
        setOps({ basemapFallback: false });
        return style;
      })
      .catch((err: unknown) => {
        toast(`Basemap unavailable (${err instanceof Error ? err.message : String(err)}); showing built-in outlines`, "warn");
        setOps({ basemapFallback: true });
        return outlineStyle();
      })
      .then((style) => !cancelled && map.setStyle(style, { diff: false }))
      .catch((err: unknown) => toast(`Basemap unavailable: ${err instanceof Error ? err.message : String(err)}`, "warn"));
    return () => {
      cancelled = true;
    };
  }, [basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTo) return;
    const options = {
      center: [flyTo.lon, flyTo.lat] as [number, number],
      zoom: flyTo.zoom ?? Math.max(map.getZoom(), FLY_DEFAULT_ZOOM),
      padding: { top: 0, bottom: 80, left: 0, right: DRAWER_PAD },
    };
    if (reduced) map.jumpTo(options);
    else map.flyTo({ ...options, duration: 1600, essential: true });
  }, [flyTo, reduced]);

  return <div ref={container} className="map" onContextMenu={(e) => e.preventDefault()} aria-label="Operational map" />;
}
