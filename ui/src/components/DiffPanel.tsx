import { useMemo, useState } from "react";

import type { Branch, GraphNode } from "../api/types";
import { formatIso } from "../lib/format";
import { glyphForNode } from "../lib/glyphs";
import { clearDiff, runDiff, selectNode } from "../state/actions";
import { setOps, useOps } from "../state/store";
import { Glyph } from "./Glyph";

const LIST_LIMIT = 40;

interface RefOption {
  value: string;
  label: string;
}

export function refOptions(branches: Branch[]): RefOption[] {
  const main = branches.find((b) => b.id === "main");
  const commits = (main?.commits ?? [])
    .slice()
    .reverse()
    .map((c) => ({ value: `main@${c.hash}`, label: `main · C${c.index}${c.time ? ` · ${formatIso(c.time)}` : ""}` }));
  const others = branches.filter((b) => b.id !== "main").map((b) => ({ value: b.id, label: `${b.label} (#${b.id})` }));
  return [{ value: "main", label: "main · HEAD" }, ...others, ...commits];
}

function NodeList({ nodes, tone }: { nodes: GraphNode[]; tone: "white" | "red" | "amber" }) {
  return (
    <ul className={`dlist dlist--${tone}`}>
      {nodes.slice(0, LIST_LIMIT).map((n) => (
        <li key={n.id}>
          <button type="button" className="nrow" onClick={() => void selectNode(n, { fly: n.lat != null })}>
            <Glyph name={glyphForNode(n)} size={13} />
            <span className="nrow__name">{n.name}</span>
          </button>
        </li>
      ))}
      {nodes.length > LIST_LIMIT ? <li className="dlist__more mono">+{nodes.length - LIST_LIMIT} more</li> : null}
    </ul>
  );
}

export function DiffPanel() {
  const open = useOps((s) => s.diffOpen);
  const diff = useOps((s) => s.diff);
  const branches = useOps((s) => s.branches);
  const activeBranch = useOps((s) => s.activeBranch);
  const options = useMemo(() => refOptions(branches), [branches]);
  const [a, setA] = useState("main");
  const [b, setB] = useState<string | null>(null);
  if (!open) return null;

  const bValue = b ?? (activeBranch !== "main" ? activeBranch : (options[options.length - 1]?.value ?? "main"));
  const result = diff?.result;
  const changedNodes = result?.changed.map((c) => c.node) ?? [];

  return (
    <section className="diff glass" aria-label="Diff">
      <header className="diff__head">
        <h3>Diff</h3>
        <button type="button" className="iconbtn" aria-label="Close diff" onClick={() => setOps({ diffOpen: false })}>
          ×
        </button>
      </header>
      <div className="diff__refs">
        <label>
          <span>From</span>
          <select value={a} onChange={(e) => setA(e.target.value)}>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>To</span>
          <select value={bValue} onChange={(e) => setB(e.target.value)}>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="diff__actions">
          <button type="button" className="btn" disabled={diff?.loading} onClick={() => void runDiff(a, bValue)}>
            {diff?.loading ? "Comparing" : "Compare"}
          </button>
          {result ? (
            <button type="button" className="btn btn--quiet" onClick={clearDiff}>
              Clear
            </button>
          ) : null}
        </div>
      </div>
      {result ? (
        <div className="diff__result">
          <div className="diff__summary mono">
            {result.a} → {result.b}
          </div>
          <div className="diff__counts">
            <span className="dcount dcount--white">+{result.added.length} appeared</span>
            <span className="dcount dcount--red">−{result.removed.length} disappeared</span>
            <span className="dcount dcount--amber">~{result.changed.length} changed</span>
          </div>
          {result.added.length ? <NodeList nodes={result.added} tone="white" /> : null}
          {result.removed.length ? <NodeList nodes={result.removed} tone="red" /> : null}
          {changedNodes.length ? <NodeList nodes={changedNodes} tone="amber" /> : null}
        </div>
      ) : null}
    </section>
  );
}
