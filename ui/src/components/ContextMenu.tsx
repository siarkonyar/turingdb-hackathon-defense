import { useEffect, useRef } from "react";

import { glyphForNode } from "../lib/glyphs";
import { canStrike, flyToNode, selectNode, simulateLoss } from "../state/actions";
import { runCascadeFor } from "../state/cascade";
import { activeOverlay, setOps, useOps } from "../state/store";
import { Glyph } from "./Glyph";

export function ContextMenu() {
  const menu = useOps((s) => s.contextMenu);
  const lost = useOps((s) => (s.contextMenu ? activeOverlay(s).entries.get(s.contextMenu.node.id)?.status === "lost" : false));
  const busy = useOps((s) => s.busy);
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menu) return;
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOps({ contextMenu: null });
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  if (!menu) return null;
  const { node } = menu;
  const strikable = canStrike(node) && !lost;
  return (
    <div className="ctxmenu glass" style={{ left: menu.x + 6, top: menu.y + 6 }} role="menu" aria-label={node.name}>
      <div className="ctxmenu__head">
        <Glyph name={glyphForNode(node)} size={14} />
        <span>{node.name}</span>
      </div>
      <button
        ref={first}
        type="button"
        role="menuitem"
        className="ctxmenu__item ctxmenu__item--danger"
        disabled={!strikable || busy !== null}
        onClick={() => void simulateLoss(node)}
      >
        <Glyph name="lost" size={13} />
        Simulate loss
        <span className="ctxmenu__hint">{lost ? "already lost" : strikable ? "new branch" : "not an asset"}</span>
      </button>
      {["chokepoint", "port", "facility"].includes(node.kind) ? (
        <button type="button" role="menuitem" className="ctxmenu__item" onClick={() => void runCascadeFor(node.id, node.name)}>
          What breaks if this falls?
          <span className="ctxmenu__hint">impact degrees</span>
        </button>
      ) : null}
      <button type="button" role="menuitem" className="ctxmenu__item" onClick={() => void selectNode(node)}>
        Open details
      </button>
      <button
        type="button"
        role="menuitem"
        className="ctxmenu__item"
        onClick={() => {
          setOps({ contextMenu: null });
          flyToNode(node);
        }}
      >
        Fly to
      </button>
    </div>
  );
}
