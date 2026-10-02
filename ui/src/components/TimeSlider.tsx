import { useCallback, useEffect, useMemo, useRef, type KeyboardEvent, type PointerEvent } from "react";

import type { Commit } from "../api/types";
import { formatUtc } from "../lib/format";
import { isoToEpoch } from "../lib/time";
import { runDiff, setTime } from "../state/actions";
import { setOps, useOps } from "../state/store";

const PLAY_SECONDS = 45; // full timeline replays in 45 s
const KEY_STEPS = 200;
const EMPTY_COMMITS: Commit[] = [];

function pct(t: number, [t0, t1]: [number, number]): string {
  return `${(((t - t0) / Math.max(1, t1 - t0)) * 100).toFixed(3)}%`;
}

export function TimeSlider() {
  const domain = useOps((s) => s.domain);
  const time = useOps((s) => s.time);
  const playing = useOps((s) => s.playing);
  const reports = useOps((s) => s.reports);
  const tracks = useOps((s) => s.tracks);
  const commits = useOps((s) => s.branches.find((b) => b.id === "main")?.commits ?? EMPTY_COMMITS);
  const track = useRef<HTMLDivElement>(null);

  const timeAt = useCallback(
    (clientX: number) => {
      const el = track.current;
      if (!el || !domain) return null;
      const r = el.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
      return domain[0] + f * (domain[1] - domain[0]);
    },
    [domain],
  );

  useEffect(() => {
    if (!playing || !domain) return;
    let raf = 0;
    let last = performance.now();
    const rate = (domain[1] - domain[0]) / PLAY_SECONDS;
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const next = useOps.getState().time + dt * rate;
      setTime(next);
      if (next >= domain[1]) setOps({ playing: false });
      else raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, domain]);

  const droneWindow = useMemo(() => {
    const stamps = tracks.flatMap((t) => [t.timestamps[0], t.timestamps[t.timestamps.length - 1]]).filter((x): x is number => x != null);
    return stamps.length ? ([Math.min(...stamps), Math.max(...stamps)] as [number, number]) : null;
  }, [tracks]);

  const datedCommits = commits
    .map((c, i) => ({ c, prev: commits[i - 1], t: isoToEpoch(c.time) }))
    .filter((x): x is { c: Commit; prev: Commit; t: number } => x.t !== null && x.prev !== undefined);

  if (!domain) return <div className="timeline timeline--empty">No timestamps on this graph yet</div>;

  const onPointer = (e: PointerEvent<HTMLDivElement>) => {
    if (e.type === "pointerdown") (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
    else if (!(e.buttons & 1)) return;
    const t = timeAt(e.clientX);
    if (t !== null) {
      setOps({ playing: false });
      setTime(t);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const span = (domain[1] - domain[0]) / KEY_STEPS;
    const moves: Record<string, number> = { ArrowRight: time + span, ArrowLeft: time - span, Home: domain[0], End: domain[1] };
    const next = moves[e.key];
    if (next !== undefined) {
      e.preventDefault();
      setTime(next);
    }
  };

  return (
    <div className="timeline">
      <button
        type="button"
        className="iconbtn timeline__play"
        aria-label={playing ? "Pause replay" : "Replay"}
        onClick={() => {
          if (!playing && time >= domain[1]) setTime(domain[0]);
          setOps({ playing: !playing });
        }}
      >
        {playing ? (
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
            <rect x="2" y="1.5" width="2.6" height="9" fill="currentColor" />
            <rect x="7.4" y="1.5" width="2.6" height="9" fill="currentColor" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
            <path d="M3 1.5L10.5 6L3 10.5Z" fill="currentColor" />
          </svg>
        )}
      </button>
      <div className="timeline__clock mono">{formatUtc(time)}</div>
      <div
        ref={track}
        className="timeline__track"
        role="slider"
        tabIndex={0}
        aria-label="Timeline"
        aria-valuemin={domain[0]}
        aria-valuemax={domain[1]}
        aria-valuenow={Math.round(time)}
        aria-valuetext={formatUtc(time)}
        onPointerDown={onPointer}
        onPointerMove={onPointer}
        onKeyDown={onKey}
      >
        <div className="timeline__rail" />
        {droneWindow ? (
          <div
            className="timeline__band"
            style={{ left: pct(droneWindow[0], domain), width: `calc(${pct(droneWindow[1], domain)} - ${pct(droneWindow[0], domain)})` }}
            title="Drone telemetry"
          />
        ) : null}
        <div className="timeline__fill" style={{ width: pct(time, domain) }} />
        {reports.map((r) => {
          const t = isoToEpoch(r.node.timestamp);
          return t === null ? null : (
            <span key={r.node.id} className={`timeline__tick${t <= time ? " is-past" : ""}`} style={{ left: pct(t, domain) }} />
          );
        })}
        {datedCommits.map(({ c, prev, t }) => (
          <button
            key={c.hash}
            type="button"
            className="timeline__commit mono"
            style={{ left: pct(t, domain) }}
            title={`Commit ${c.hash.slice(0, 8)}: +${c.node_delta} nodes. Click to diff against the previous commit.`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => {
              setOps({ playing: false });
              setTime(t);
              void runDiff(`main@${prev.hash}`, `main@${c.hash}`);
            }}
          >
            C{c.index}
          </button>
        ))}
        <div className="timeline__thumb" style={{ left: pct(time, domain) }} />
      </div>
    </div>
  );
}
