import type { Move } from "../api/types";
import { latencyText, signedPct, type MatchView } from "../lib/match";

const SIDE_NAME = { red: "Red", blue: "Blue", inject: "Event" } as const;

function MoveCard({ move }: { move: Move }) {
  const tag = move.side === "inject" ? "EVENT" : move.round === 0 ? "PREPARATION" : `R${move.round} · ${move.side.toUpperCase()}`;
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
      {move.selection && (move.selection.candidates?.length || move.selection.fallback) ? (
        <div className="mcard__why">
          {move.selection.selector === "jev" ? "Jev selected" : "Blue selected"}
          {move.selection.candidates.length ? ` from ${move.selection.candidates.length} alternatives` : ""}
          {move.selection.fallback ? " · used existing decision flow" : ""}.
        </div>
      ) : null}
      <div className="mcard__loss mono">
        <span className={move.loss_pct > 0 ? "is-worse" : move.loss_pct < 0 ? "is-better" : undefined}>
          {signedPct(move.loss_pct)} vs base
        </span>
        <span className="mcard__abs">{move.abs_loss_pct.toFixed(1)}% total · #{move.branch_id}</span>
      </div>
      {move.breakdown?.deep_pct != null ? (
        <div className="mcard__split mono" title="Absolute loss on each layer: the deep supply network (platform production) and the original parts layer">
          deep network {move.breakdown.deep_pct.toFixed(1)}% · parts layer {(move.breakdown.legacy_pct ?? 0).toFixed(1)}%
        </div>
      ) : null}
      {move.strategy?.budget_total ? (
        <div className="mcard__strategy">
          <p className="mono">Credits {move.strategy.budget_remaining}/{move.strategy.budget_total}
            {move.side === "blue" ? ` · spent ${move.strategy.cost ?? 0} · ready R${move.strategy.ready_round}` : ""}</p>
          {move.strategy.planning?.future_loss_pct != null ? <p>Forecast after {move.strategy.planning.response}:
            {" "}{move.strategy.planning.future_loss_pct.toFixed(1)}% loss by R{move.strategy.planning.horizon_round}.</p> : null}
          {move.strategy.alternatives?.map((a) => <p key={a.label}>Alternative: {a.label} · {a.cost} credits · ready R{a.ready_round}
            {a.planning?.future_loss_pct != null ? ` · forecast ${a.planning.future_loss_pct.toFixed(1)}% loss` : ""}</p>)}
        </div>
      ) : null}
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
