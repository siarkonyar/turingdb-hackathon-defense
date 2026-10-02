import { describe, expect, it } from "vitest";

import type { DiffResponse, GraphNode, Report, SimulateResponse, Track } from "../api/types";
import { queryString } from "../api/client";
import { arcTrips, arrivalTimes, curvedPath, drawDuration } from "./arcs";
import { formatCoord, formatInt, formatIso, formatLatency, formatMw, formatPercent, formatUtc, formatValue, humanRel } from "./format";
import { GLYPHS, glyphForFuel, glyphForNode } from "./glyphs";
import { EMPTY_OVERLAY, diffClasses, escalate, kpisFromOverlay, mergeSimulation, overlayFromDiff } from "./overlay";
import { clampedPositionAt, epochToIso, isoToEpoch, newlyArrived, positionAt, reportsUntil, timelineDomain } from "./time";
import { ALWAYS_VISIBLE, filterValue, glyphSize, minCapacityForZoom } from "./zoom";

const node = (id: string, label: string, extra: Partial<GraphNode> = {}): GraphNode => ({
  id,
  kind: (
    { PowerPlant: "plant", Site: "site", Supplier: "supplier", Drone: "drone", Part: "part", Report: "report" } as const
  )[label as "Site"] ?? "other",
  label,
  name: id,
  lat: 50,
  lon: 5,
  importance: 0.5,
  ...extra,
});

const timed = { engine: "fixtures" as const, latency_ms: 1, roundtrip_ms: 2 };

const report = (id: string, ts: string): Report => ({
  node: node(id, "Report", { timestamp: ts }),
  report_id: id,
  text: "",
  mentions: [],
});

describe("zoom filtering", () => {
  it("shows only large plants at continental zoom and everything when zoomed in", () => {
    expect(minCapacityForZoom(2)).toBe(2400);
    expect(minCapacityForZoom(1)).toBe(2400);
    expect(minCapacityForZoom(4)).toBeLessThan(minCapacityForZoom(3));
    expect(minCapacityForZoom(8)).toBe(0);
    expect(minCapacityForZoom(Number.NaN)).toBe(0);
  });

  it("pins statused nodes above any threshold and sizes glyphs by importance", () => {
    expect(filterValue(5, true)).toBe(ALWAYS_VISIBLE);
    expect(filterValue(null, false)).toBe(0);
    expect(glyphSize(0)).toBe(9);
    expect(glyphSize(1)).toBe(26);
    expect(glyphSize(7)).toBe(26);
  });
});

describe("cascade arcs", () => {
  it("draws a curve that starts and ends on the endpoints", () => {
    const path = curvedPath([0, 0], [10, 0], 10);
    expect(path).toHaveLength(11);
    expect(path[0]).toEqual([0, 0]);
    expect(path[10]?.[0]).toBeCloseTo(10);
    expect(path[5]?.[1]).toBeGreaterThan(0); // bowed, not straight
  });

  it("delays deeper hops and clamps draw time", () => {
    expect(drawDuration([0, 0], [0, 0.001])).toBe(380);
    expect(drawDuration([0, 0], [90, 0])).toBe(1100);
    const arcs = [
      { source: [0, 0], target: [1, 1], source_id: "a", target_id: "b", hop: 1, rel: "POWERED_BY" },
      { source: [1, 1], target: [2, 2], source_id: "b", target_id: "c", hop: 2, rel: "PATROLS" },
    ] as SimulateResponse["arcs"];
    const { trips, durationMs } = arcTrips(arcs, false);
    expect(trips[1]?.timestamps[0]).toBeGreaterThan(trips[0]?.timestamps[0] ?? 0);
    expect(durationMs).toBeGreaterThan(500);
    const arrivals = arrivalTimes(trips);
    expect(arrivals.get("c")).toBe(durationMs);
  });

  it("completes instantly with reduced motion", () => {
    const arcs = [{ source: [0, 0], target: [3, 3], source_id: "a", target_id: "b", hop: 3, rel: "X" }] as SimulateResponse["arcs"];
    const { trips, durationMs } = arcTrips(arcs, true);
    expect(durationMs).toBe(0);
    expect(new Set(trips[0]?.timestamps)).toEqual(new Set([0]));
  });
});

describe("overlay", () => {
  const diff: DiffResponse = {
    ...timed,
    a: "main",
    b: "1",
    added: [node("new", "Report")],
    removed: [node("p1", "PowerPlant")],
    changed: [
      { node: node("s1", "Site", { status: "at_risk" }), fields: { status: [null, "at_risk"] } },
      { node: node("s2", "Site"), fields: { name: ["a", "b"] } },
      { node: node("x1", "Part", { lat: null, lon: null }), fields: { status: [null, "at_risk"] } },
    ],
  };

  it("derives statuses from a diff and ignores non-status changes", () => {
    const o = overlayFromDiff(diff);
    expect(o.entries.get("p1")?.status).toBe("lost");
    expect(o.entries.get("s1")?.status).toBe("at_risk");
    expect(o.entries.has("s2")).toBe(false);
    expect(o.added).toHaveLength(1);
    expect(kpisFromOverlay(o)).toEqual({ assets_at_risk: 1, sites_without_power: 0, suppliers_without_power: 0, parts_affected: 1 });
  });

  it("merges a stacked strike without downgrading statuses and without mutating the base", () => {
    const base = overlayFromDiff(diff);
    const sim: SimulateResponse = {
      ...timed,
      branch: "1",
      base_branch: "1",
      struck: node("p2", "PowerPlant"),
      affected: [
        { node: node("s1", "Site", { status: "no_power" }), hop: 1, via: "POWERED_BY", parent_id: "p2" },
        { node: node("d1", "Drone", { status: "at_risk" }), hop: 2, via: "PATROLS", parent_id: "s1" },
      ],
      lost: [],
      arcs: [],
      kpis: { assets_at_risk: 0, sites_without_power: 0, suppliers_without_power: 0, parts_affected: 0 },
    };
    const merged = mergeSimulation(base, sim);
    expect(merged.entries.get("s1")?.status).toBe("no_power");
    expect(merged.entries.get("p2")?.status).toBe("lost");
    expect(base.entries.has("p2")).toBe(false);
    expect(kpisFromOverlay(merged).sites_without_power).toBe(1);
    expect(escalate("no_power", "at_risk")).toBe("no_power");
    expect(kpisFromOverlay(EMPTY_OVERLAY).assets_at_risk).toBe(0);
  });

  it("classifies diff entries for the map", () => {
    const classes = diffClasses(diff);
    expect(classes.get("new")?.cls).toBe("added");
    expect(classes.get("p1")?.cls).toBe("removed");
    expect(classes.get("s2")?.cls).toBe("changed");
  });
});

describe("timeline", () => {
  const track: Track = { id: "d", name: "d", path: [[0, 0], [0, 10]], timestamps: [100, 200] };

  it("converts between ISO and epoch seconds", () => {
    expect(isoToEpoch("2026-09-29T05:00:00Z")).toBe(1790658000);
    expect(epochToIso(1790658000)).toBe("2026-09-29T05:00:00Z");
    expect(isoToEpoch("nope")).toBeNull();
    expect(isoToEpoch(null)).toBeNull();
  });

  it("spans reports, tracks and commits with padding", () => {
    const domain = timelineDomain([report("r", "2026-09-29T05:00:00Z")], [track], [{ hash: "h", index: 0, node_delta: 0, edge_delta: 0 }]);
    expect(domain).toEqual([100 - 600, 1790658000 + 600]);
    expect(timelineDomain([], [], [])).toBeNull();
  });

  it("interpolates track positions and heading", () => {
    const p = positionAt(track, 150);
    expect(p?.lat).toBeCloseTo(5);
    expect(p?.headingDeg).toBeCloseTo(0);
    expect(positionAt(track, 99)).toBeNull();
    expect(positionAt(track, 201)).toBeNull();
    expect(clampedPositionAt(track, 999)?.lat).toBeCloseTo(10);
    expect(clampedPositionAt(track, 0)?.lat).toBeCloseTo(0);
    expect(clampedPositionAt({ ...track, timestamps: [1], path: [[0, 0]] }, 5)).toBeNull();
  });

  it("finds reports visible at t and those that just arrived", () => {
    const reports = [report("a", "2026-09-29T05:00:00Z"), report("b", "2026-09-29T06:00:00Z")];
    const t5 = isoToEpoch("2026-09-29T05:30:00Z") as number;
    expect(reportsUntil(reports, t5).map((r) => r.report_id)).toEqual(["a"]);
    expect(newlyArrived(reports, t5, t5 + 3600).map((r) => r.report_id)).toEqual(["b"]);
    expect(newlyArrived(reports, t5 + 3600, t5)).toEqual([]);
  });
});

describe("formatting", () => {
  it("formats latency, numbers and units for mono display", () => {
    expect(formatLatency(0.04)).toBe("<0.1");
    expect(formatLatency(3.14)).toBe("3.1");
    expect(formatLatency(1234.4)).toBe("1,234");
    expect(formatLatency(undefined)).toBe("—");
    expect(formatInt(12345)).toBe("12,345");
    expect(formatMw(884)).toBe("884 MW");
    expect(formatMw(2400)).toBe("2.4 GW");
    expect(formatPercent(0.64)).toBe("64%");
  });

  it("formats coordinates, times, relationships and values", () => {
    expect(formatCoord(53.4, -2.3)).toBe("53.4000°N  2.3000°W");
    expect(formatCoord(null, 1)).toBe("—");
    expect(formatUtc(1790658540)).toBe("29 Sep 05:09Z");
    expect(formatIso("2026-09-29T05:09:00Z")).toBe("29 Sep 05:09Z");
    expect(humanRel("POWERED_BY")).toBe("Powered by");
    expect(formatValue(true)).toBe("yes");
    expect(formatValue(2.123456)).toBe("2.1235");
    expect(formatValue(null)).toBe("—");
  });
});

describe("glyphs and api helpers", () => {
  it("maps fuels and kinds to defined glyphs", () => {
    expect(glyphForFuel("Nuclear")).toBe("plant-nuclear");
    expect(glyphForFuel("Mystery")).toBe("plant-other");
    expect(glyphForNode({ kind: "site" })).toBe("site");
    expect(glyphForNode({ kind: "plant", fuel: "Wind" })).toBe("plant-wind");
    for (const parts of Object.values(GLYPHS)) expect(parts.length).toBeGreaterThan(0);
  });

  it("builds query strings without empty parameters", () => {
    expect(queryString({ a: "main", b: undefined, c: "" })).toBe("?a=main");
    expect(queryString({})).toBe("");
  });
});
