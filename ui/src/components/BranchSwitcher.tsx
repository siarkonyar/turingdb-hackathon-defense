import { useEffect, useRef } from "react";

import type { Branch } from "../api/types";
import { formatPercent } from "../lib/format";
import { discardBranch, switchBranch } from "../state/actions";
import { activeBranchInfo, setOps, useOps } from "../state/store";

const KIND_LABEL: Record<Branch["kind"], string> = {
  main: "Main",
  hypothesis: "Hypothesis",
  strike: "Strike",
  change: "Change",
};

function Confidence({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  return (
    <span className="conf" title={`confidence ${formatPercent(value)}`}>
      <span className="conf__bar">
        <span style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="mono">{formatPercent(value)}</span>
    </span>
  );
}

function Row({ branch, active }: { branch: Branch; active: boolean }) {
  return (
    <li className={`brow${active ? " is-active" : ""}`}>
      <button type="button" className="brow__main" onClick={() => void switchBranch(branch.id)}>
        <span className="brow__label">{branch.label}</span>
        {branch.kind === "hypothesis" ? <Confidence value={branch.confidence} /> : null}
        {branch.kind !== "main" ? <span className="brow__id mono">#{branch.id}</span> : null}
      </button>
      {branch.kind === "strike" ? (
        <button
          type="button"
          className="iconbtn brow__discard"
          aria-label={`Discard ${branch.label}`}
          title="Discard this strike branch (TuringDB CHANGE DELETE)"
          onClick={() => void discardBranch(branch.id)}
        >
          ×
        </button>
      ) : null}
    </li>
  );
}

export function BranchSwitcher() {
  const branches = useOps((s) => s.branches);
  const activeId = useOps((s) => s.activeBranch);
  const active = useOps(activeBranchInfo);
  const open = useOps((s) => s.branchMenuOpen);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOps({ branchMenuOpen: false });
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);

  const groups: { title: string; items: Branch[] }[] = [
    { title: "Baseline", items: branches.filter((b) => b.kind === "main") },
    { title: "Hypotheses", items: branches.filter((b) => b.kind === "hypothesis") },
    { title: "Strike simulations", items: branches.filter((b) => b.kind === "strike") },
    { title: "Other changes", items: branches.filter((b) => b.kind === "change") },
  ].filter((g) => g.items.length);

  return (
    <div className="branches" ref={ref}>
      <button
        type="button"
        className="branches__btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOps({ branchMenuOpen: !open })}
      >
        <span className="branches__kind">{KIND_LABEL[active?.kind ?? "main"]}</span>
        <span className="branches__label">{active?.label ?? "main"}</span>
        {active?.kind === "hypothesis" ? <span className="mono branches__conf">{formatPercent(active.confidence)}</span> : null}
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
          <path d="M2 6.5L5 3.5L8 6.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      </button>
      {open ? (
        <div className="branches__menu glass" role="listbox" aria-label="Branches">
          {groups.map((g) => (
            <div key={g.title}>
              <div className="branches__group">{g.title}</div>
              <ul>
                {g.items.map((b) => (
                  <Row key={b.id} branch={b} active={b.id === activeId} />
                ))}
              </ul>
            </div>
          ))}
          <p className="branches__hint">Right-click an asset on the map to simulate its loss on a new branch.</p>
        </div>
      ) : null}
    </div>
  );
}
