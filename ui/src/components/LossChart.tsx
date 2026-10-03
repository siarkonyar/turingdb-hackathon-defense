import { useMemo, useState } from "react";

import { lossSeries, signedPct, type LossPoint } from "../lib/match";

const W = 368;
const H = 132;
const PAD = { l: 34, r: 10, t: 10, b: 20 };
const MARK = 4.5; // >= 9 px markers
const HIT = 11;

interface Props {
  moves: Parameters<typeof lossSeries>[0];
  rounds: number;
  baseLossPct: number;
}

function niceMax(v: number): number {
  return Math.max(10, Math.ceil((v + 2) / 10) * 10);
}

function Marker({ p, x, y }: { p: LossPoint; x: number; y: number }) {
  if (p.side === "blue") return <rect className="lchart__mark lchart__mark--blue" x={x - MARK} y={y - MARK} width={MARK * 2} height={MARK * 2} rx={1.5} />;
  if (p.side === "inject")
    return <path className="lchart__mark lchart__mark--inject" d={`M${x} ${y - MARK - 1}L${x + MARK + 1} ${y}L${x} ${y + MARK + 1}L${x - MARK - 1} ${y}Z`} />;
  return <circle className="lchart__mark lchart__mark--red" cx={x} cy={y} r={MARK} />;
}

/** Absolute projected loss after every move; the dashed line is the base branch (the scenario). */
export function LossChart({ moves, rounds, baseLossPct }: Props) {
  const points = useMemo(() => lossSeries(moves), [moves]);
  const [hover, setHover] = useState<number | null>(null);
  const yMax = niceMax(Math.max(baseLossPct, ...points.map((p) => p.y)));
  const xMax = Math.max(rounds, 1, ...points.map((p) => Math.ceil(p.x)));
  const sx = (x: number) => PAD.l + (x / xMax) * (W - PAD.l - PAD.r);
  const sy = (y: number) => PAD.t + (1 - y / yMax) * (H - PAD.t - PAD.b);
  const ticks = [0, yMax / 2, yMax];
  const path = [{ x: 0, y: baseLossPct }, ...points].map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)} ${sy(p.y).toFixed(1)}`).join("");
  const hovered = hover === null ? null : points[hover];

  return (
    <figure className="lchart" aria-label="Projected loss per round">
      <figcaption className="lchart__legend">
        <span><i className="lkey lkey--red" aria-hidden /> Red</span>
        <span><i className="lkey lkey--blue" aria-hidden /> Blue</span>
        <span><i className="lkey lkey--inject" aria-hidden /> Event</span>
        <span><i className="lkey lkey--base" aria-hidden /> Base {baseLossPct.toFixed(1)}%</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Loss after each move" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="lchart__grid" x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} />
            <text className="lchart__tick" x={PAD.l - 6} y={sy(t) + 3.5} textAnchor="end">
              {t}%
            </text>
          </g>
        ))}
        {Array.from({ length: xMax }, (_, i) => (
          <text key={i} className="lchart__tick" x={sx(i + 0.5)} y={H - 5} textAnchor="middle">
            R{i + 1}
          </text>
        ))}
        <line className="lchart__base" x1={PAD.l} x2={W - PAD.r} y1={sy(baseLossPct)} y2={sy(baseLossPct)} />
        {points.length ? <path className="lchart__line" d={path} /> : null}
        {points.map((p, i) => (
          <g key={`${p.move.branch_id}`} onMouseEnter={() => setHover(i)}>
            <Marker p={p} x={sx(p.x)} y={sy(p.y)} />
            <circle className="lchart__hit" cx={sx(p.x)} cy={sy(p.y)} r={HIT} />
          </g>
        ))}
      </svg>
      {hovered ? (
        <div className="lchart__tip" style={{ left: `${(sx(hovered.x) / W) * 100}%` }} role="tooltip">
          <strong className="mono">{hovered.y.toFixed(1)}%</strong> <span className="mono">({signedPct(hovered.move.loss_pct)} vs base)</span>
          <div>{hovered.move.label}</div>
        </div>
      ) : null}
    </figure>
  );
}
