import { branchTree, type MatchView } from "../lib/match";
import { pickTreeNode } from "../state/wargame";
import { useOps } from "../state/store";

/** scenario → R1 → B1 → EV1 → R2 …  Click: show on the map. Shift-click two: diff them. */
export function BranchTree({ view }: { view: MatchView }) {
  const active = useOps((s) => s.activeBranch);
  const pick = useOps((s) => s.wargame.treePick);
  const nodes = branchTree(view);
  if (!nodes.length) return null;
  return (
    <div className="btree">
      <ol className="btree__chain" aria-label="Match branches">
        {nodes.map((n, i) => (
          <li key={n.id} className="btree__item">
            {i ? <span className="btree__edge" aria-hidden>→</span> : null}
            <button
              type="button"
              className={`btree__node btree__node--${n.side}${n.id === active ? " is-active" : ""}${n.id === pick ? " is-picked" : ""}`}
              title={`${n.label} (#${n.id})${n.id === pick ? " — shift-click another node to diff" : ""}`}
              aria-pressed={n.id === active}
              onClick={(e) => pickTreeNode(n.id, e.shiftKey)}
            >
              <span className="mono">{n.tag}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="btree__hint">{pick ? `#${pick} picked: shift-click a second node to diff.` : "Click a node to show it. Shift-click two to diff."}</p>
    </div>
  );
}
