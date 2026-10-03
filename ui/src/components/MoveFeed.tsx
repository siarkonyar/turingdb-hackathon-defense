import type { Move } from "../api/types";
import { latencyText, signedPct, type MatchView } from "../lib/match";

const SIDE_NAME = { red: "Red", blue: "Blue", inject: "Event" } as const;

function MoveCard({ move }: { move: Move }) {
  const tag = move.side === "inject" ? "EVENT" : `R${move.round} · ${move.side.toUpperCase()}`;
  return (
    <li className={`mcard mcard--${move.side}`}>
      <div className="mcard__top">
        <span className="mcard__tag mono">{tag}</span>
        <span className="mcard__lat mono" title={`total ${Math.round(move.latency_ms)} ms`}>
          {latencyText(move)}
        </span>
      </div>
      <div className="mcard__label">{move.label}</div>
      <div className="mcard__why" title={move.rationale}>
        {move.fallback ? <span className="chip chip--quiet">default</span> : null} {move.rationale}
      </div>
      <div className="mcard__loss mono">
        <span className={move.loss_pct > 0 ? "is-worse" : move.loss_pct < 0 ? "is-better" : undefined}>
          {signedPct(move.loss_pct)} vs base
        </span>
        <span className="mcard__abs">{move.abs_loss_pct.toFixed(1)}% total · #{move.branch_id}</span>
      </div>
    </li>
  );
}

/** One card per move, newest first; a placeholder card while a side is choosing. */
export function MoveFeed({ view }: { view: MatchView }) {
  const moves = [...view.moves].reverse();
  return (
    <ol className="mfeed" aria-label="Moves" aria-live="polite">
      {view.pending ? (
        <li className={`mcard mcard--${view.pending.side} mcard--pending`}>
          <span className="spinner" aria-hidden />
          {view.pending.side === "inject"
            ? `Applying event: ${view.pending.text ?? ""}`
            : `${SIDE_NAME[view.pending.side]} is choosing a move (round ${view.pending.round})…`}
        </li>
      ) : null}
      {moves.map((m) => (
        <MoveCard key={m.branch_id} move={m} />
      ))}
    </ol>
  );
}
