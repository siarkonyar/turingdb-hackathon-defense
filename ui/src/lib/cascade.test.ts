import { describe, expect, it } from "vitest";

import type { CascadeHit, CascadeResponse, CascadeStage, GraphNode } from "../api/types";
import {
  DEGREE_COLORS,
  MAX_LABELS_PER_DEGREE,
  cascadeFocus,
  clampStep,
  currentStage,
  degreeColor,
  degreeCss,
  headline,
  ordinal,
  stepLabel,
  topHits,
  visibleStages,
} from "./cascade";

const node = (id: string, lon: number, lat: number, kind: GraphNode["kind"] = "facility"): GraphNode => ({
  id, kind, label: kind === "facility" ? "Facility" : "Chokepoint", name: `N${id}`, lon, lat, importance: 0.5,
});

const hit = (id: string, degree: number, severity: number, lon = 10, lat = 50): CascadeHit => ({
  node: node(id, lon, lat), degree, severity, parent_id: "0", via: degree === 1 ? "TRANSITED" : "SUPPLIES",
});

const stage = (degree: number, hits: CascadeHit[]): CascadeStage => ({
  degree, hits, arcs: [], count: hits.length,
  mean_severity: hits.reduce((a, h) => a + h.severity, 0) / Math.max(1, hits.length),
});

const result = (stages: CascadeStage[]): CascadeResponse => ({
  engine: "turingdb", latency_ms: 23.4, roundtrip_ms: 80, queries: [{ cypher: "q", ms: 8 }, { cypher: "r", ms: 15.4 }],
  branch: "main", origin: { ...node("0", 56.4, 26.5, "chokepoint"), name: "Strait of Hormuz", status: "lost" },
  origin_kind: "chokepoint", min_severity: 0.05, stages, max_degree: stages.length,
  graph_hops: stages.length ? stages.length + 1 : 0,
  total_affected: stages.reduce((a, s) => a + s.count, 0),
  reach: { cypher: "MATCH ...{1,12}...", depth_limit: 12, reached: 2262, ms: 8.2 }, platforms: [],
});

const hormuz = result([
  stage(1, [hit("a", 1, 1), hit("b", 1, 0.5, 20, 40)]),
  stage(2, [hit("c", 2, 0.4, 30, 30)]),
  stage(3, [hit("d", 3, 0.1, 40, 20)]),
]);

describe("degree colours and ordinals", () => {
  it("gives a distinct colour per degree and clamps beyond the palette", () => {
    expect(new Set(DEGREE_COLORS.map((c) => c.join())).size).toBe(DEGREE_COLORS.length);
    expect(degreeColor(1)).toEqual(DEGREE_COLORS[0]);
    expect(degreeColor(99)).toEqual(DEGREE_COLORS[DEGREE_COLORS.length - 1]);
    expect(degreeColor(0)).toEqual(DEGREE_COLORS[0]);
    expect(degreeCss(1)).toBe(`rgb(${DEGREE_COLORS[0]!.slice(0, 3).join(" ")})`);
  });
  it("formats English ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]);
  });
});

describe("stepping", () => {
  it("clamps the step to 0..max_degree", () => {
    expect(clampStep(-1, hormuz)).toBe(0);
    expect(clampStep(2, hormuz)).toBe(2);
    expect(clampStep(9, hormuz)).toBe(3);
  });
  it("reveals degrees up to the step", () => {
    expect(visibleStages(hormuz, 0)).toEqual([]);
    expect(visibleStages(hormuz, 2).map((s) => s.degree)).toEqual([1, 2]);
    expect(currentStage(hormuz, 0)).toBeNull();
    expect(currentStage(hormuz, 2)?.degree).toBe(2);
  });
  it("labels each step", () => {
    expect(stepLabel(hormuz, 0)).toBe("Strait of Hormuz closed. Impact reaches 3 degrees: press Continue for the 1st degree.");
    expect(stepLabel(hormuz, 1)).toBe("1st degree of 3: 2 facilities lose supply (mean 75% of inbound volume).");
    expect(stepLabel(hormuz, 3)).toBe("3rd degree of 3: 1 facility loses supply (mean 10% of inbound volume). End of the cascade.");
    expect(stepLabel(result([]), 0)).toBe("Strait of Hormuz closed. No facility loses at least 5% of its supply.");
  });
});

describe("headline", () => {
  it("summarises TuringDB speed and depth", () => {
    expect(headline(hormuz)).toEqual({
      degrees: 3, hops: 4, affected: 4, reached: 2262, reachMs: 8.2, totalMs: 23.4, queries: 2, depthLimit: 12,
    });
  });
});

describe("topHits", () => {
  it("returns the highest-severity hits, capped", () => {
    const many = stage(1, Array.from({ length: 30 }, (_, i) => hit(`h${i}`, 1, 1 - i / 100)));
    expect(topHits(many).length).toBe(MAX_LABELS_PER_DEGREE);
    expect(topHits(many, 3).map((h) => h.node.id)).toEqual(["h0", "h1", "h2"]);
  });
});

describe("cascadeFocus", () => {
  it("centres on the origin at step 0 and on the revealed stage afterwards", () => {
    expect(cascadeFocus(hormuz, 0)).toEqual({ lon: 56.4, lat: 26.5, zoom: 4 });
    const f = cascadeFocus(hormuz, 1);
    expect(f.lon).toBeCloseTo(15);
    expect(f.lat).toBeCloseTo(45);
    expect(f.zoom).toBeGreaterThanOrEqual(1.8);
    expect(f.zoom).toBeLessThanOrEqual(6);
  });
});
