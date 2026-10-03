import { useEffect } from "react";

import { useDoverProfile } from "../hooks/useDoverProfile";
import type { GraphNode, NeighbourGroup } from "../api/types";
import { formatCoord, formatIso, formatMw, formatValue, humanRel } from "../lib/format";
import { glyphForNode } from "../lib/glyphs";
import { canStrike, closeDrawer, selectNode, simulateLoss } from "../state/actions";
import { activeOverlay, useOps } from "../state/store";
import { Glyph } from "./Glyph";
import { StatusChip } from "./StatusChip";

const HIDDEN_PROPS = new Set(["name", "latitude", "longitude", "ops_status"]);
const PROP_LIMIT = 18;

function NeighbourRow({ node }: { node: GraphNode }) {
  const status = useOps((s) => activeOverlay(s).entries.get(node.id)?.status);
  const located = node.lat != null && node.lon != null;
  const meta = node.kind === "plant" ? formatMw(node.capacity_mw) : node.kind === "report" ? formatIso(node.timestamp) : node.label;
  return (
    <li>
      <button
        type="button"
        className="nrow"
        onClick={() => void selectNode(node, { fly: located })}
        title={located ? "Select and fly to" : "Select"}
      >
        <Glyph name={glyphForNode(node)} size={14} />
        <span className="nrow__name">{node.name}</span>
        {status ? <StatusChip status={status} /> : <span className="nrow__meta mono">{meta}</span>}
      </button>
    </li>
  );
}

function Group({ group }: { group: NeighbourGroup }) {
  const arrow = group.direction === "out" ? "→" : "←";
  return (
    <section className="ngroup">
      <header className="ngroup__head">
        <span>
          <span className="mono ngroup__arrow">{arrow}</span> {humanRel(group.rel)}
        </span>
        <span className="mono ngroup__count">{group.total.toLocaleString("en-GB")}</span>
      </header>
      <ul>
        {group.nodes.map((n) => (
          <NeighbourRow key={`${group.rel}-${group.direction}-${n.id}`} node={n} />
        ))}
      </ul>
      {group.total > group.nodes.length ? (
        <div className="ngroup__more mono">+{(group.total - group.nodes.length).toLocaleString("en-GB")} more</div>
      ) : null}
    </section>
  );
}

export function NodeDrawer() {
  const dover = useDoverProfile();
  const drawer = useOps((s) => s.drawer);
  const fallback = useOps((s) => (s.drawer ? s.nodeIndex.get(s.drawer.nodeId) : undefined));
  const status = useOps((s) => (s.drawer ? activeOverlay(s).entries.get(s.drawer.nodeId)?.status : undefined));
  const busy = useOps((s) => s.busy);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeDrawer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  if (!drawer) return null;
  const node = drawer.data?.node ?? fallback;
  const props = Object.entries(drawer.data?.properties ?? {}).filter(([k]) => !HIDDEN_PROPS.has(k));

  return (
    <aside className="drawer glass" aria-label="Node details">
      <header className="drawer__head">
        <div className="drawer__title">
          {node ? <Glyph name={glyphForNode(node)} size={20} /> : null}
          <h2>{node?.name ?? "Loading"}</h2>
        </div>
        <button type="button" className="iconbtn" onClick={closeDrawer} aria-label="Close details">
          ×
        </button>
      </header>
      {node ? (
        <div className="drawer__sub">
          <span className="chip">{node.label}</span>
          {status ? <StatusChip status={status} /> : null}
          {node.synthetic ? <span className="chip chip--quiet">synthetic</span> : null}
          <span className="mono drawer__id">#{node.id}</span>
        </div>
      ) : null}
      {node ? <div className="drawer__coord mono">{formatCoord(node.lat, node.lon)}</div> : null}
      {!dover && node && canStrike(node) && status !== "lost" ? (
        <button type="button" className="btn btn--danger" disabled={busy !== null} onClick={() => void simulateLoss(node)}>
          <Glyph name="lost" size={13} /> Simulate loss
        </button>
      ) : null}
      {drawer.note ? <p className="drawer__note">{drawer.note}</p> : null}
      {drawer.error ? <p className="drawer__error">{drawer.error}</p> : null}
      <div className="drawer__body">
        {drawer.loading ? (
          <div className="skeleton" aria-busy="true">
            <span />
            <span />
            <span />
          </div>
        ) : null}
        {props.length ? (
          <section className="props">
            <h3>Properties</h3>
            <dl>
              {props.slice(0, PROP_LIMIT).map(([k, v]) => (
                <div key={k} className="props__row">
                  <dt>{k}</dt>
                  <dd className="mono">{formatValue(v)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}
        {drawer.data?.groups.length ? (
          <section className="neighbours">
            <h3>Neighbours</h3>
            {drawer.data.groups.map((g) => (
              <Group key={`${g.rel}-${g.direction}`} group={g} />
            ))}
          </section>
        ) : null}
      </div>
    </aside>
  );
}
