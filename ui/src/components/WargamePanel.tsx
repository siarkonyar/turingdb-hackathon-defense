import { isLive, type MatchView } from "../lib/match";
import { useOps } from "../state/store";
import {
  controlMatch,
  injectEvent,
  runOneShot,
  setFollow,
  setWargame,
  setWargameOpen,
  startMatch,
  startReplay,
} from "../state/wargame";
import { BranchTree } from "./BranchTree";
import { LossChart } from "./LossChart";
import { MoveFeed } from "./MoveFeed";
import { ScenarioPrompt } from "./ScenarioPrompt";

const ROUND_CHOICES = [1, 2, 3, 4, 5, 6];

function LlmChip() {
  const status = useOps((s) => s.wargame.status);
  if (!status) return <span className="chip chip--quiet">LLM …</span>;
  return status.available ? (
    <span className="chip chip--quiet mono" title={status.model}>
      LLM ready
    </span>
  ) : (
    <span className="chip chip--red" title={status.reason}>
      LLM offline
    </span>
  );
}

function Setup({ disabled }: { disabled: boolean }) {
  const w = useOps((s) => s.wargame);
  const branches = useOps((s) => s.branches);
  const bases = branches.filter((b) => b.kind === "main" || b.kind === "scenario");
  const llmDown = w.status !== null && !w.status.available;
  return (
    <div className="wg__setup">
      <label>
        <span>Base</span>
        <select value={w.base} disabled={disabled} onChange={(e) => setWargame({ base: e.target.value })}>
          {bases.map((b) => (
            <option key={b.id} value={b.id}>
              {b.id === "main" ? "main · nominal" : `${b.label} (#${b.id})`}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Rounds</span>
        <select value={w.rounds} disabled={disabled} onChange={(e) => setWargame({ rounds: Number(e.target.value) })}>
          {ROUND_CHOICES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="btn btn--go" disabled={disabled || llmDown} onClick={() => void startMatch()}>
        Start
      </button>
    </div>
  );
}

function Replay({ disabled, emphasise }: { disabled: boolean; emphasise: boolean }) {
  const saved = useOps((s) => s.wargame.saved);
  const file = useOps((s) => s.wargame.replayFile);
  return (
    <div className={`wg__replay${emphasise ? " is-emphasised" : ""}`}>
      <select value={file} disabled={disabled || !saved.length} onChange={(e) => setWargame({ replayFile: e.target.value })} aria-label="Saved match">
        {saved.length ? null : <option value="">no saved matches</option>}
        {saved.map((m) => (
          <option key={m.file} value={m.file}>
            {m.file} · {m.moves} moves{m.final_loss_pct != null ? ` · +${m.final_loss_pct}%` : ""}
          </option>
        ))}
      </select>
      <button type="button" className="btn" disabled={disabled || !file} onClick={() => void startReplay()} title="Plays a recorded match back with its original timing and no LLM calls">
        Replay saved match
      </button>
    </div>
  );
}

function Controls({ view }: { view: MatchView }) {
  const follow = useOps((s) => s.wargame.follow);
  const paused = view.phase === "paused";
  return (
    <div className="wg__controls">
      {!view.replay ? (
        <button type="button" className="btn" onClick={() => void controlMatch(paused ? "resume" : "pause")}>
          {paused ? "Resume" : "Pause"}
        </button>
      ) : null}
      <button type="button" className="btn btn--stop" onClick={() => void controlMatch("stop")}>
        Stop
      </button>
      <label className="wg__follow">
        <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Map follows head
      </label>
    </div>
  );
}

function StatusLine({ view }: { view: MatchView }) {
  const played = view.moves.filter((m) => m.side === "blue").length;
  const last = view.moves[view.moves.length - 1];
  const label =
    view.phase === "starting" ? "Starting…" : view.phase === "paused" ? "Paused" : view.phase === "running" ? "Live" : view.phase;
  return (
    <div className="wg__status">
      <span className={`wg__phase wg__phase--${view.phase}`}>{view.replay ? `Replay · ${label}` : label}</span>
      <span className="mono">
        round {Math.min(played + (isLive(view) ? 1 : 0), view.rounds || 1)}/{view.rounds || "–"}
      </span>
      {last ? <span className="mono">head #{last.branch_id}</span> : null}
      {view.model && !view.replay ? <span className="mono wg__model">{view.model.split("/").pop()}</span> : null}
    </div>
  );
}

function Inject({ view }: { view: MatchView }) {
  const text = useOps((s) => s.wargame.injectText);
  const note = useOps((s) => s.wargame.injectNote);
  return (
    <section className="wg__inject" aria-label="Inject an event">
      <h4>Inject event</h4>
      <ScenarioPrompt
        label="Event to inject"
        rows={2}
        value={text}
        onChange={(t) => setWargame({ injectText: t, injectNote: null })}
        onSubmit={() => void injectEvent()}
        disabled={!isLive(view)}
        submitLabel="Inject"
        placeholder="the Liverpool port is closed"
      >
        {note ? <span className="wg__note">{note}</span> : null}
      </ScenarioPrompt>
    </section>
  );
}

function OneShot({ disabled }: { disabled: boolean }) {
  const o = useOps((s) => s.wargame.oneShot);
  const last = o.steps[o.steps.length - 1];
  return (
    <details className="wg__oneshot">
      <summary>One-shot red vs blue</summary>
      <p className="scenario__hint">
        The free-form threat agent explores attacks, then the defence agent answers the worst one. Slower than
        a match (many tool calls), streamed live.
      </p>
      <button type="button" className="btn" disabled={disabled || o.running} onClick={() => void runOneShot()}>
        {o.running ? "Running…" : "Run red vs blue"}
      </button>
      {o.running ? (
        <p className="scenario__status">
          <span className="spinner" aria-hidden /> {o.steps.length} steps
          {last ? (
            <>
              {" "}· <span className="mono">{last.agent}:{last.action}</span>
            </>
          ) : null}
        </p>
      ) : null}
      {o.result?.headline ? <p className="scenario__explain">{o.result.headline}</p> : null}
      {o.result?.selection && (o.result.selection.candidates.length || o.result.selection.fallback) ? (
        <p className="scenario__explain">
          {o.result.selection.selector === "jev" ? "Jev selected the defence" : "Blue selected the defence"}
          {o.result.selection.fallback ? " using the existing decision flow" : ""}.
        </p>
      ) : null}
      {o.error ? <p className="scenario__err mono">{o.error}</p> : null}
    </details>
  );
}

/** The wargame: set up a match, watch red and blue take turns on the map, inject events, replay. */
export function WargamePanel() {
  const open = useOps((s) => s.wargame.open);
  const view = useOps((s) => s.wargame.view);
  const status = useOps((s) => s.wargame.status);
  if (!open) return null;
  const live = isLive(view);
  const llmDown = status !== null && !status.available;

  return (
    <aside className="wg glass" aria-label="Wargame">
      <header className="wg__head">
        <h3>Wargame</h3>
        <LlmChip />
        <button type="button" className="iconbtn" aria-label="Close wargame" onClick={() => setWargameOpen(false)}>
          ×
        </button>
      </header>
      {llmDown ? (
        <p className="wg__alert">
          The LLM backend is unavailable ({status?.reason}). Live matches cannot start, but a saved match replays
          without it.
        </p>
      ) : null}
      <Setup disabled={live} />
      <Replay disabled={live} emphasise={llmDown || (view.phase === "error" && view.replayAvailable)} />
      {view.phase !== "idle" ? (
        <>
          <StatusLine view={view} />
          {live ? <Controls view={view} /> : null}
          {view.error ? <p className="scenario__err mono">{view.error}</p> : null}
          {view.baseBranch ? <LossChart moves={view.moves} rounds={view.rounds} baseLossPct={view.baseLossPct} /> : null}
          <BranchTree view={view} />
          {live && !view.replay ? <Inject view={view} /> : null}
          <MoveFeed view={view} />
        </>
      ) : (
        <p className="scenario__hint">
          Pick a base (simulate a scenario first, e.g. “everything in Manchester is destroyed”), then Start. Each
          round red makes one disruption and blue one countermeasure, each a TuringDB branch stacked on the last.
        </p>
      )}
      <OneShot disabled={live || llmDown} />
    </aside>
  );
}
