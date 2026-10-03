# Plan A — Impact Cascade ("Hormuz closed: what breaks, degree by degree") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator asks "What happens if the Strait of Hormuz closes?", and the map first
shows the headline: *one deep TuringDB query, N degrees, M graph hops, X ms*. Then **Continue** reveals the
impact one degree at a time. Degree 1 links appear from the origin, then degree 2 links from the degree-1
facilities, and so on to the last degree. Every degree has its own colour, its number on the map, and a row in
a degree ladder.

**Architecture:** A pure, offline-tested propagation engine (`api/deep_cascade.py`) runs volume-weighted BFS
over the deep `SUPPLIES` network. A live module (`api/deep_cascade_live.py`) reads the network, seeds and
facility coordinates from TuringDB on any ref (main or a branch). It also runs and times **one deep
variable-length query** (`-[:SUPPLIES]->{1,12}`) as the speed proof. New read-only routes (`/cascade/*`)
serve a `CascadeResponse` split into per-degree stages. The UI keeps a `step` in a store slice. The map layer
draws the stages up to `step` and animates the arcs of the newest degree. Plan B reuses the engine, the
stepper component and the map layer unchanged.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, TuringDB 3.0 Python SDK, pytest; React 19, zustand 5,
deck.gl 9 (ScatterplotLayer, PathLayer, TripsLayer, TextLayer), vitest.

**Spec:** `docs/superpowers/plans/2026-10-03-cascade-contract.md` (read it first; it is binding) + the user's
request in this session: "When the user asks what happens if Hormuz closes, first show
how many steps deep the impact went, together with TuringDB's speed ('query asked, 8 steps taken in this many
seconds'). Then show step by step which nodes were affected at which degree: first the links of step 1 on the
map; pressing a Continue-like button shows the links to the 2nd-degree nodes, and so on to the last step. The
degree of every step must be clear and visible on the map. If 8 steps were walked, show them one by one, not
all at once."

## Global Constraints

- Branch: `feat/impact-cascade` in its own git worktree (contract § Git workflow). Do not touch Plan B's files.
- `MIN_SEVERITY = 0.05`, `MAX_DEGREE = 12` (contract § Domain model). Severity formula exactly as in the contract.
- Read-only: Plan A never creates a branch and never writes the graph. `/cascade` works on `main` or any
  existing branch ref.
- Routes are mounted only when `settings.backend == "turingdb"`; mounting failure logs a warning, never crashes.
- Python: `from __future__ import annotations`, typed, frozen dataclasses / `Frozen` pydantic models, short
  module docstring explaining *why*, no new dependencies.
- UI: state is replaced, never mutated (zustand `setOps` with new objects). No new npm dependencies.
- UI copy and the question box are English (English place names and aliases, Task A3).
- Every `CascadeResponse` carries `Timed` fields (`latency_ms`, `roundtrip_ms`, `queries`) from the `Stopwatch`.
- Server for live work: in-memory `theatre` (contract § Runtime rules).

## Review Focus

1. **Question with no recognisable place** ("what happens tomorrow?") → 422 with an empty `candidates` list;
   the panel says "No chokepoint, port or facility recognised" and offers example chips. Pinned in A4
   (`test_ask_unknown_place_is_422_with_candidates`) and A6 (panel error state).
2. **Ambiguous question** ("Busan Hamburg") → 422 with ≥ 2 candidates, rendered as clickable chips that run
   the cascade for that origin. Pinned in A3 (`test_pick_requires_margin`) and A4.
3. **Origin with zero downstream impact** (a facility with no buyers, or a chokepoint no consignment transits)
   → 200, `stages == []`, `max_degree == 0`; the stepper shows "No facility loses at least 5% of its supply" and
   Continue is disabled. Pinned in A1 (`test_no_buyers_yields_no_layers`) and A5 (`stepLabel` for 0 stages).
4. **Large cascades** (Taiwan Strait: ~3,900 hits, ~1,000 ms reach query) must not freeze the map: arc paths
   are built once per stage (WeakMap cache), only the current degree animates, and badges are capped at 8 per
   degree. Pinned in A5 (`topHits` cap), A7 (`stagePaths` cache test) and A8 (manual check with Taiwan Strait).
5. **Continue at the last degree / Back at step 0 / switching origin mid-animation** → step is clamped, the
   animation restarts cleanly, and the old layers vanish. Pinned in A5 (`clampStep`) and A6 (every action
   resets `stepStartedAt`; `showCascade` resets `step` to 0).

---

## File Structure

| File | Responsibility |
|---|---|
| `api/models.py` (modify) | `chokepoint` kind; `OriginKind`, `CascadeHit`, `CascadeStage`, `ReachProbe`, `PlatformExposure`, `CascadeRequest`, `CascadeAskRequest`, `OriginCandidate`, `OriginsResponse`, `CascadeResponse` |
| `api/nodes.py` (modify) | `Chokepoint` → `chokepoint` kind + importance |
| `api/backends/base.py` (modify) | `NODE_KINDS` gains `chokepoint` |
| `api/backends/turing.py` (modify) | `KIND_QUERIES`/`SNAPSHOT_KINDS`/`meta.layers` gain chokepoint; public `session()` |
| `api/deep_cascade.py` (create) | Pure engine: `SupplyNetwork`, `Seeds`, `Hit`, `propagate`, `impact_score` |
| `api/deep_cascade_live.py` (create) | `DeepCascade`: TuringDB reads, caching, reach probe, `compute()` → `CascadeResponse` |
| `api/cascade_resolve.py` (create) | Pure place-name resolution with English aliases |
| `api/cascade_routes.py` (create) | `/cascade/origins`, `/cascade`, `/cascade/ask` |
| `api/main.py` (modify) | mount the routes when live |
| `tests/api/test_deep_cascade.py` (create) | engine unit tests |
| `tests/api/test_cascade_resolve.py` (create) | resolver unit tests |
| `tests/api/test_cascade_routes.py` (create) | HTTP tests with a fake engine |
| `tests/api/test_deep_cascade_live.py` (create) | live TuringDB tests (skip when the server is down) |
| `ui/src/api/types.ts`, `ui/src/api/client.ts` (modify) | mirrored types; `cascadeOrigins`, `cascade`, `cascadeAsk`; `ApiError.body` |
| `ui/src/lib/cascade.ts` (create) | pure helpers: colours, ordinals, step clamping, labels, focus |
| `ui/src/lib/cascade.test.ts` (create) | vitest for the helpers |
| `ui/src/state/store.ts` (modify) | `cascade` slice + `chokepoint` base kind |
| `ui/src/state/cascade.ts` (create) | actions: ask, run, show, next/prev/all/reset/goTo, clear |
| `ui/src/components/CascadeStepper.tsx` (create) | headline + degree ladder + controls + current-degree list |
| `ui/src/components/CascadePanel.tsx` (create) | the "Impact" panel: question box, candidate chips, stepper |
| `ui/src/components/BottomBar.tsx`, `ContextMenu.tsx`, `LayerRail.tsx` (modify) | entry points |
| `ui/src/map/cascadeLayers.ts` (create) | deck.gl layers for origin, revealed degrees, current-degree animation |
| `ui/src/map/MapView.tsx`, `ui/src/map/layers.ts`, `ui/src/map/colors.ts` (modify) | wire the cascade layers; chokepoint base layer |
| `ui/src/state/actions.ts` (modify) | `BASE_KINDS` includes chokepoint |
| `ui/src/styles/app.css` (modify, append) | `/* cascade */` section |
| `docs/api.md`, `AGENTS.md` (modify) | contract + handoff notes |

---

### Task A1: Contract models, chokepoint kind, pure propagation engine

**Files:**
- Modify: `api/models.py`, `api/nodes.py`, `api/backends/base.py`
- Create: `api/deep_cascade.py`
- Test: `tests/api/test_deep_cascade.py`

**Interfaces:**
- Consumes: `api.models.Frozen`, `Node`, `Arc`, `Timed` (existing).
- Produces: every model in contract § API shapes; `api.deep_cascade.{MIN_SEVERITY, MAX_DEGREE, SupplyNetwork,
  Seeds, Hit, propagate, impact_score}` with exactly the contract signatures, plus
  `SupplyNetwork.from_edges(rows: Iterable[tuple[str, str, float | None]]) -> SupplyNetwork`.

- [ ] **Step 1: Write the failing engine tests**

Create `tests/api/test_deep_cascade.py`:

```python
"""Volume-weighted cascade engine (pure). Networks are hand-built so every severity is checkable by hand."""

from __future__ import annotations

import pytest

from api.deep_cascade import MAX_DEGREE, Hit, Seeds, SupplyNetwork, impact_score, propagate


def net(*edges: tuple[str, str, float]) -> SupplyNetwork:
    return SupplyNetwork.from_edges(edges)


def by_degree(layers: list[list[Hit]]) -> list[dict[str, float]]:
    return [{h.facility_id: h.severity for h in layer} for layer in layers]


def test_from_edges_sums_inbound_and_treats_missing_volume_as_zero():
    n = net(("A", "C", 6.0), ("B", "C", 4.0), ("A", "D", None))  # type: ignore[arg-type]
    assert n.inbound == {"C": 10.0, "D": 0.0}
    assert n.out_edges["A"] == (("C", 6.0), ("D", 0.0))


def test_chain_attenuates_by_inbound_share():
    n = net(("A", "B", 10.0), ("B", "C", 5.0), ("X", "C", 15.0))
    layers = propagate(Seeds({"A": 1.0}, degree=1, via="TRANSITED"), n)
    assert by_degree(layers) == [{"A": 1.0}, {"B": 1.0}, {"C": 0.25}]
    assert [h.degree for layer in layers for h in layer] == [1, 2, 3]
    assert layers[0][0].parent is None and layers[0][0].via == "TRANSITED"
    assert layers[2][0].parent == "B" and layers[2][0].via == "SUPPLIES"


def test_below_threshold_is_dropped_and_does_not_propagate():
    n = net(("A", "B", 1.0), ("Y", "B", 99.0), ("B", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), n, min_severity=0.05)
    assert by_degree(layers) == [{"A": 1.0}]  # B gets 0.01 < 0.05, so C is never reached


def test_multiple_affected_suppliers_add_up_and_parent_is_biggest_contributor():
    n = net(("A", "C", 6.0), ("B", "C", 4.0), ("Z", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0, "B": 0.5}, 1, "TRANSITED"), n)
    hit = layers[1][0]
    assert hit.facility_id == "C" and hit.severity == pytest.approx(0.4)  # (6*1 + 4*0.5) / 20
    assert hit.parent == "A"


def test_parent_tie_goes_to_smaller_facility_id():
    n = net(("B", "C", 5.0), ("A", "C", 5.0))
    layers = propagate(Seeds({"A": 1.0, "B": 1.0}, 1, "TRANSITED"), n)
    assert layers[1][0].parent == "A"


def test_node_is_assigned_once_at_its_first_degree():
    n = net(("A", "B", 1.0), ("A", "C", 1.0), ("B", "C", 1.0))
    layers = propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), n)
    assert [sorted(d) for d in by_degree(layers)] == [["A"], ["B", "C"]]


def test_facility_origin_is_not_returned_and_cycles_terminate():
    n = net(("O", "B", 1.0), ("B", "O", 1.0), ("B", "C", 1.0))
    layers = propagate(Seeds({"O": 1.0}, degree=0, via="SUPPLIES"), n)
    assert by_degree(layers) == [{"B": 1.0}, {"C": 1.0}]
    assert layers[0][0].degree == 1 and layers[0][0].parent == "O"


def test_no_buyers_yields_no_layers():
    assert propagate(Seeds({"O": 1.0}, 0, "SUPPLIES"), net(("X", "Y", 1.0))) == []


def test_seeds_below_threshold_are_dropped():
    layers = propagate(Seeds({"A": 0.02, "B": 0.9}, 1, "TRANSITED"), net())
    assert by_degree(layers) == [{"B": 0.9}]


def test_layers_sorted_by_severity_then_id():
    layers = propagate(Seeds({"B": 0.5, "A": 0.5, "C": 0.9}, 1, "TRANSITED"), net())
    assert [h.facility_id for h in layers[0]] == ["C", "A", "B"]


def test_max_degree_caps_depth():
    chain = [(f"F{i}", f"F{i + 1}", 1.0) for i in range(30)]
    layers = propagate(Seeds({"F0": 1.0}, 1, "TRANSITED"), net(*chain))
    assert len(layers) == MAX_DEGREE and layers[-1][0].degree == MAX_DEGREE
    assert len(propagate(Seeds({"F0": 1.0}, 1, "TRANSITED"), net(*chain), max_degree=3)) == 3


def test_severity_is_capped_at_one():
    n = net(("A", "C", 10.0), ("B", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0, "B": 1.0}, 1, "TRANSITED"), n)
    assert layers[1][0].severity == 1.0


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_invalid_min_severity_raises(bad: float):
    with pytest.raises(ValueError):
        propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), net(), min_severity=bad)


def test_invalid_seed_degree_raises():
    with pytest.raises(ValueError):
        propagate(Seeds({"A": 1.0}, 2, "TRANSITED"), net())


def test_impact_score_sums_severity_to_two_decimals():
    layers = [[Hit("A", 1, 1.0, None, "TRANSITED")], [Hit("B", 2, 0.333, "A", "SUPPLIES"),
                                                      Hit("C", 2, 0.25, "A", "SUPPLIES")]]
    assert impact_score(layers) == 1.58
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/api/test_deep_cascade.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'api.deep_cascade'`.

- [ ] **Step 3: Implement the engine**

Create `api/deep_cascade.py`:

```python
"""Volume-weighted impact cascade over the deep supply network (pure: no I/O).

Why weighted: unweighted reach from one chokepoint touches half of all facilities and every platform, which
tells an operator nothing. Severity is the share of a facility's inbound supply volume that comes from
already-affected suppliers, so impact attenuates with depth and the map shows where it really bites.
Breadth-first: each facility is reported once, at the first degree that reaches it above the threshold.
Contract: docs/superpowers/plans/2026-10-03-cascade-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

MIN_SEVERITY = 0.05
MAX_DEGREE = 12
SEVERITY_DP = 3


@dataclass(frozen=True)
class SupplyNetwork:
    out_edges: Mapping[str, tuple[tuple[str, float], ...]]  # supplier facility_id -> ((buyer, volume), ...)
    inbound: Mapping[str, float]  # buyer facility_id -> total inbound volume over all its suppliers

    @staticmethod
    def from_edges(rows: Iterable[tuple[str, str, float | None]]) -> SupplyNetwork:
        out: dict[str, list[tuple[str, float]]] = {}
        inbound: dict[str, float] = {}
        for src, dst, volume in rows:
            v = max(0.0, float(volume or 0.0))
            out.setdefault(src, []).append((dst, v))
            inbound[dst] = inbound.get(dst, 0.0) + v
        return SupplyNetwork(out_edges={k: tuple(v) for k, v in out.items()}, inbound=inbound)


@dataclass(frozen=True)
class Seeds:
    severities: Mapping[str, float]  # facility_id -> severity in (0, 1]
    degree: int  # 1: seeds are the first affected facilities (chokepoint/port); 0: the seed is the lost origin
    via: str  # edge that carried the impact to the seeds: TRANSITED | LOADED_AT | SUPPLIES


@dataclass(frozen=True)
class Hit:
    facility_id: str
    degree: int
    severity: float
    parent: str | None  # parent facility_id; None when the parent is the (non-facility) origin
    via: str


def _sorted(items: Iterable[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(items, key=lambda kv: (-kv[1], kv[0]))


def _seed_layer(seeds: Seeds, min_severity: float) -> list[Hit]:
    kept = _sorted((fid, min(1.0, s)) for fid, s in seeds.severities.items() if s >= min_severity)
    return [Hit(fid, 1, round(s, SEVERITY_DP), None, seeds.via) for fid, s in kept]


def _next_layer(frontier: Sequence[str], severity: Mapping[str, float], seen: set[str],
                network: SupplyNetwork, degree: int, min_severity: float) -> list[Hit]:
    contrib: dict[str, float] = {}
    best: dict[str, tuple[float, str]] = {}
    for supplier in sorted(frontier):  # sorted: a tie on contribution keeps the smaller supplier id
        for buyer, volume in network.out_edges.get(supplier, ()):
            total = network.inbound.get(buyer, 0.0)
            if buyer in seen or total <= 0:
                continue
            share = severity[supplier] * volume / total
            contrib[buyer] = contrib.get(buyer, 0.0) + share
            if buyer not in best or share > best[buyer][0]:
                best[buyer] = (share, supplier)
    kept = _sorted((b, min(1.0, s)) for b, s in contrib.items() if s >= min_severity)
    return [Hit(b, degree, round(s, SEVERITY_DP), best[b][1], "SUPPLIES") for b, s in kept]


def propagate(seeds: Seeds, network: SupplyNetwork, min_severity: float = MIN_SEVERITY,
              max_degree: int = MAX_DEGREE) -> list[list[Hit]]:
    """Layers of hits, index 0 = degree 1. A facility origin (seed degree 0) is never returned itself."""
    if not 0 < min_severity <= 1:
        raise ValueError(f"min_severity must be in (0, 1], got {min_severity}")
    if seeds.degree not in (0, 1):
        raise ValueError(f"seed degree must be 0 or 1, got {seeds.degree}")
    layers: list[list[Hit]] = []
    if seeds.degree == 1:
        first = _seed_layer(seeds, min_severity)
        if not first:
            return []
        layers.append(first)
        severity = {h.facility_id: h.severity for h in first}
    else:
        severity = {fid: min(1.0, s) for fid, s in seeds.severities.items()}
    seen = set(severity)
    frontier = list(severity)
    degree = seeds.degree
    while frontier and degree < max_degree:
        degree += 1
        layer = _next_layer(frontier, severity, seen, network, degree, min_severity)
        if not layer:
            break
        layers.append(layer)
        for h in layer:
            severity[h.facility_id] = h.severity
            seen.add(h.facility_id)
        frontier = [h.facility_id for h in layer]
    return layers


def impact_score(layers: Sequence[Sequence[Hit]]) -> float:
    """Facility-equivalents of output disrupted: Σ severity over every hit (the origin is not a hit)."""
    return round(sum(h.severity for layer in layers for h in layer), 2)
```

Note: propagation uses the rounded (3 dp) severities. The prototype numbers in the contract were computed
unrounded; small differences in deep tails are expected and fine.

- [ ] **Step 4: Run the engine tests**

Run: `uv run pytest tests/api/test_deep_cascade.py -q`
Expected: all pass.

- [ ] **Step 5: Add the contract models and the chokepoint kind**

In `api/models.py`:

```python
Kind = Literal["plant", "site", "supplier", "drone", "crime", "report", "part", "facility", "port", "chokepoint",
               "other"]
OriginKind = Literal["chokepoint", "port", "facility"]
LOCATED_KINDS: tuple[str, ...] = ("plant", "site", "supplier", "drone", "crime", "report", "facility", "port",
                                  "chokepoint")
```

Append after `SimulateResponse`:

```python
# ---------------------------------------------------------------- impact cascade (supply_chain_deep)


class CascadeHit(Frozen):
    node: Node
    degree: int
    severity: float  # share of inbound supply volume lost, 0..1
    parent_id: str | None
    via: str  # TRANSITED | LOADED_AT | SUPPLIES


class CascadeStage(Frozen):
    degree: int
    hits: list[CascadeHit]
    arcs: list[Arc]
    count: int
    mean_severity: float


class ReachProbe(Frozen):
    cypher: str
    depth_limit: int
    reached: int
    ms: float | None


class PlatformExposure(Frozen):
    name: str
    archetype: str | None = None
    severity: float
    facility_id: str


class CascadeRequest(Frozen):
    origin_id: str = Field(min_length=1, max_length=64)
    branch: str = Field(default="main", min_length=1, max_length=64)
    min_severity: float = Field(default=0.05, ge=0.01, le=0.5)


class CascadeAskRequest(Frozen):
    question: str = Field(min_length=2, max_length=400)
    branch: str = Field(default="main", min_length=1, max_length=64)
    min_severity: float = Field(default=0.05, ge=0.01, le=0.5)


class OriginCandidate(Frozen):
    node: Node
    origin_kind: OriginKind
    score: float


class OriginsResponse(Frozen):
    query: str
    candidates: list[OriginCandidate]


class CascadeResponse(Timed):
    branch: str
    origin: Node
    origin_kind: OriginKind
    min_severity: float
    stages: list[CascadeStage]
    max_degree: int
    graph_hops: int
    total_affected: int
    reach: ReachProbe
    platforms: list[PlatformExposure]
```

In `api/nodes.py`, add `"Chokepoint": "chokepoint",` to `KIND_BY_LABEL` and `"chokepoint": 0.9,` to
`FIXED_IMPORTANCE`. In `api/backends/base.py`, add `"chokepoint"` to the end of `NODE_KINDS`.

- [ ] **Step 6: Add a node-normalisation test for chokepoints**

Append to `tests/api/test_deep_cascade.py`:

```python
def test_chokepoint_nodes_normalise_with_coordinates():
    from api.nodes import make_node

    node = make_node(7, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4})
    assert node.kind == "chokepoint" and node.lat == 26.5 and node.lon == 56.4 and node.importance == 0.9
```

- [ ] **Step 7: Run the whole offline API suite**

Run: `uv run pytest tests/api -q`
Expected: all pass (live tests skip or pass). The mock backend still serves `/nodes?types=chokepoint` with an
empty list (check: `uv run pytest tests/api/test_routes.py -q` passes).

- [ ] **Step 8: Commit**

```bash
git add api/deep_cascade.py api/models.py api/nodes.py api/backends/base.py tests/api/test_deep_cascade.py
git commit -m "feat: volume-weighted deep supply cascade engine and contract models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A2: Live engine over TuringDB (`DeepCascade`)

**Files:**
- Modify: `api/backends/turing.py`
- Create: `api/deep_cascade_live.py`
- Test: `tests/api/test_deep_cascade_live.py`

**Interfaces:**
- Consumes: A1 engine + models; `api.backends.turing_session.{Session, node_id_literal, string_literal}`;
  `api.backends.turing.{TuringBackend, NODE_PROPS, ENGINE}`; `api.nodes.{clean, with_status, is_located}`;
  `api.support.{Stopwatch, NotFound}`; `api.refs.Ref`.
- Produces: `TuringBackend.session(ref, sw) -> Session`; `api.deep_cascade_live.{Origin, FacilityIndex,
  DeepCascade}` exactly as in contract § Cross-boundary Python interface; module helpers
  `build_stages(origin: Origin, layers, index: FacilityIndex) -> list[CascadeStage]` and
  `platform_exposure(origin: Origin, layers, index) -> list[PlatformExposure]`.

- [ ] **Step 1: Make sure the live server is up, in-memory**

```bash
uv run turingdb stop -turing-dir "$(pwd)"
uv run turingdb start -turing-dir "$(pwd)" -demon -in-memory -load theatre -start-timeout 20000
```
Expected: server on :6666 (`curl -s localhost:6666 >/dev/null && echo up`). If `graphs/theatre` is missing,
build it first with `uv run python fusion/build_theatre.py` (~2 min), then stop and restart as above. If
another session is using the server (check `CHANGE LIST`), do not restart it; coordinate with the user.

- [ ] **Step 2: Write the failing live tests**

Create `tests/api/test_deep_cascade_live.py`:

```python
"""Impact cascade against the live `theatre` graph. Read-only: asserts that no change is created.
Skipped when the server or graph is unavailable."""

from __future__ import annotations

import os

import pytest

from api.backends.turing import ENGINE, TuringBackend
from api.refs import Ref
from api.support import Stopwatch

HOST = os.environ.get("TURINGDB_HOST", "http://localhost:6666")
GRAPH = os.environ.get("TURINGDB_GRAPH", "theatre")
REACH_BUDGET_MS = 500  # Hormuz measured at ~8 ms engine time; generous for a laptop under load


def _reachable() -> bool:
    try:
        from turingdb import TuringDB

        return GRAPH in TuringDB(host=HOST).list_available_graphs()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason=f"TuringDB {HOST} with graph {GRAPH} not available")


@pytest.fixture(scope="module")
def engine():
    from api.deep_cascade_live import DeepCascade

    return DeepCascade(TuringBackend(HOST, GRAPH))


def origin_id(engine, name: str) -> str:
    s = engine.session(Ref("main"))
    return next(n.id for n, _ in engine.catalog(s) if n.name == name)


def change_count(engine) -> int:
    return len(engine.session(Ref("main")).q("CHANGE LIST"))


def test_catalog_lists_all_chokepoints_ports_and_facilities(engine):
    kinds = [k for _, k in engine.catalog(engine.session(Ref("main")))]
    assert kinds.count("chokepoint") == 15 and kinds.count("port") == 71 and kinds.count("facility") > 4000


def test_hormuz_cascade_is_staged_weighted_and_fast(engine):
    before = change_count(engine)
    r = engine.compute(Ref("main"), origin_id(engine, "Strait of Hormuz"))
    assert r.origin.kind == "chokepoint" and r.origin.status == "lost" and r.origin_kind == "chokepoint"
    assert r.stages[0].count == 8 and r.stages[0].hits[0].via == "TRANSITED"
    assert r.max_degree == len(r.stages) >= 5 and r.graph_hops == r.max_degree + 1
    assert [st.degree for st in r.stages] == list(range(1, r.max_degree + 1))
    assert r.total_affected == sum(st.count for st in r.stages)
    assert r.reach.reached >= r.total_affected - r.stages[0].count
    assert r.reach.ms is not None and r.reach.ms < REACH_BUDGET_MS
    assert "{1,12}" in r.reach.cypher
    assert r.engine == ENGINE and r.queries
    assert change_count(engine) == before  # read-only


def test_every_hit_has_a_parent_in_the_previous_degree_and_matching_arc(engine):
    r = engine.compute(Ref("main"), origin_id(engine, "Strait of Hormuz"))
    previous = {r.origin.id}
    for stage in r.stages:
        ids = {h.node.id for h in stage.hits}
        assert all(h.parent_id in previous for h in stage.hits)
        assert all(0.05 <= h.severity <= 1 for h in stage.hits)
        assert all(a.hop == stage.degree and a.target_id in ids for a in stage.arcs)
        assert all(h.node.status == "at_risk" and h.node.lat is not None for h in stage.hits)
        previous = ids


def test_facility_origin_starts_at_its_buyers(engine):
    s = engine.session(Ref("main"))
    network, index = engine.network(s), engine.facility_index(s)
    fid = max(network.out_edges, key=lambda f: len(network.out_edges[f]))
    origin = index.by_fid[fid]
    r = engine.compute(Ref("main"), origin.id)
    assert r.origin_kind == "facility" and r.graph_hops == r.max_degree
    assert origin.id not in {h.node.id for st in r.stages for h in st.hits}
    assert all(h.parent_id == origin.id for h in r.stages[0].hits)


def test_port_origin_uses_loaded_at(engine):
    r = engine.compute(Ref("main"), origin_id(engine, "Port of Busan"))
    assert r.origin_kind == "port" and r.stages and r.stages[0].hits[0].via == "LOADED_AT"


def test_seeds_by_origin_matches_single_origin_seeds(engine):
    s = engine.session(Ref("main"))
    hormuz = engine.origin(s, origin_id(engine, "Strait of Hormuz"))
    single = engine.seeds(s, hormuz)
    grouped = engine.seeds_by_origin(s, "chokepoint")
    assert dict(grouped[hormuz.node.id].severities) == pytest.approx(dict(single.severities))
    assert len(grouped) <= 15


def test_non_origin_label_is_rejected(engine):
    s = engine.session(Ref("main"))
    plant = s.q("MATCH (n:PowerPlant) RETURN n LIMIT 1")["n"].iloc[0]
    with pytest.raises(ValueError):
        engine.compute(Ref("main"), str(plant))


def test_session_records_timing(engine):
    sw = Stopwatch(ENGINE)
    engine.session(Ref("main"), sw).q("MATCH (k:Chokepoint) RETURN count(k)")
    assert sw.traces and sw.traces[0].ms is not None
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/api/test_deep_cascade_live.py -q`
Expected: errors with `ModuleNotFoundError: api.deep_cascade_live`, not skips. If everything skips, the
server is not up: go back to Step 1.

- [ ] **Step 4: Public `session()` and chokepoint wiring in the backend**

In `api/backends/turing.py`:

```python
    "port": (("Port",), "MATCH (n:Port)", None),
    "chokepoint": (("Chokepoint",), "MATCH (n:Chokepoint)", None),  # supply_chain_deep sea chokepoints
}
SNAPSHOT_KINDS = ("plant", "site", "supplier", "drone", "report", "part", "facility", "port", "chokepoint")
```

In `meta()`, append `"chokepoint"` to `layers`. Below `_session`, add:

```python
    def session(self, ref: Ref, sw: Stopwatch) -> Session:
        """A session checked out on `ref` (validated). Public so read-only feature modules can query."""
        return self._session(ref, sw)
```

- [ ] **Step 5: Implement `api/deep_cascade_live.py`**

```python
"""Live side of the impact cascade: reads the deep supply network from TuringDB on any ref (main or a branch),
times one deep variable-length query as proof of speed, and shapes the per-degree CascadeResponse the map
steps through. Read-only. The weighting itself lives in api/deep_cascade.py (pure, unit-tested)."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Sequence, TypeVar

import pandas as pd

from api.backends.turing import ENGINE, NODE_PROPS, TuringBackend
from api.backends.turing_session import Session, node_id_literal, string_literal
from api.deep_cascade import MAX_DEGREE, MIN_SEVERITY, Hit, Seeds, SupplyNetwork, propagate
from api.models import (Arc, CascadeHit, CascadeResponse, CascadeStage, Node, OriginKind, PlatformExposure,
                        ReachProbe)
from api.nodes import clean, is_located, with_status
from api.refs import Ref
from api.support import NotFound, Stopwatch

T = TypeVar("T")
CACHE_LIMIT = 24
ORIGIN_LABELS: dict[str, OriginKind] = {"Chokepoint": "chokepoint", "Port": "port", "Facility": "facility"}
KEY_PROP: dict[str, str] = {"chokepoint": "waypoint_id", "port": "port_id", "facility": "facility_id"}
LABEL_OF: dict[str, str] = {"chokepoint": "Chokepoint", "port": "Port", "facility": "Facility"}
SEED_EDGE: dict[str, str] = {"chokepoint": "TRANSITED", "port": "LOADED_AT"}

SUPPLY_EDGES_Q = ("MATCH (a:Facility)-[e:SUPPLIES]->(b:Facility) "
                  "RETURN a.facility_id AS a, b.facility_id AS b, e.annual_volume AS v")
SHIPPED_TOTALS_Q = "MATCH (c:Consignment)-[:SHIPPED_FROM]->(f:Facility) RETURN f.facility_id AS fid, count(c) AS n"
PLATFORMS_Q = ("MATCH (p:Platform)-[:PRODUCED_AT]->(f:Facility) "
               "RETURN f.facility_id AS fid, p.name AS name, p.archetype AS archetype")


@dataclass(frozen=True)
class Origin:
    node: Node
    kind: OriginKind
    key: str


@dataclass(frozen=True)
class FacilityIndex:
    by_fid: Mapping[str, Node]
    fid_by_id: Mapping[str, str]
    platforms: Mapping[str, tuple[tuple[str, str | None], ...]]


def _shares(frame: pd.DataFrame, totals: Mapping[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    for fid, n in zip(frame["fid"], frame["n"]):
        total = totals.get(str(fid), 0)
        if total > 0:
            out[str(fid)] = min(1.0, int(n) / total)
    return out


def _arc(parent: Node, child: Node, degree: int, via: str) -> Arc | None:
    if not (is_located(parent) and is_located(child)):
        return None
    return Arc(source=(parent.lon, parent.lat), target=(child.lon, child.lat), source_id=parent.id,
               target_id=child.id, hop=degree, rel=via)


def build_stages(origin: Origin, layers: Sequence[Sequence[Hit]], index: FacilityIndex) -> list[CascadeStage]:
    stages: list[CascadeStage] = []
    for layer in layers:
        hits: list[CascadeHit] = []
        arcs: list[Arc] = []
        for h in layer:
            node = index.by_fid.get(h.facility_id)
            if node is None:
                continue
            parent = (index.by_fid.get(h.parent) if h.parent else None) or origin.node
            hits.append(CascadeHit(node=with_status(node, "at_risk"), degree=h.degree, severity=h.severity,
                                   parent_id=parent.id, via=h.via))
            arc = _arc(parent, node, h.degree, h.via)
            if arc is not None:
                arcs.append(arc)
        if hits:
            mean = round(sum(x.severity for x in hits) / len(hits), 3)
            stages.append(CascadeStage(degree=layer[0].degree, hits=hits, arcs=arcs, count=len(hits),
                                       mean_severity=mean))
    return stages


def platform_exposure(origin: Origin, layers: Sequence[Sequence[Hit]], index: FacilityIndex) -> list[PlatformExposure]:
    best: dict[str, PlatformExposure] = {}
    affected = [(h.facility_id, h.severity) for layer in layers for h in layer]
    if origin.kind == "facility":
        affected.append((origin.key, 1.0))  # the lost facility's own platforms are fully exposed
    for fid, severity in affected:
        node = index.by_fid.get(fid)
        if node is None:
            continue
        for name, archetype in index.platforms.get(fid, ()):
            if name not in best or severity > best[name].severity:
                best[name] = PlatformExposure(name=name, archetype=archetype, severity=severity, facility_id=node.id)
    return sorted(best.values(), key=lambda p: (-p.severity, p.name))


class DeepCascade:
    def __init__(self, backend: TuringBackend) -> None:
        self.backend = backend
        self._lock = threading.Lock()
        self._cache: dict[tuple, object] = {}

    # ------------------------------------------------------------------ plumbing

    def session(self, ref: Ref, sw: Stopwatch | None = None) -> Session:
        return self.backend.session(ref, sw or Stopwatch(ENGINE))

    def _cached(self, s: Session, what: str, build: Callable[[], T]) -> T:
        key = (what, s.ref.branch, s.head())
        with self._lock:
            if key in self._cache:
                return self._cache[key]  # type: ignore[return-value]
        value = build()
        with self._lock:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = value
        return value

    # ------------------------------------------------------------------ reads (cached per branch head)

    def network(self, s: Session) -> SupplyNetwork:
        def build() -> SupplyNetwork:
            frame = s.q(SUPPLY_EDGES_Q)
            return SupplyNetwork.from_edges(
                (str(a), str(b), float(clean(v) or 0.0)) for a, b, v in zip(frame["a"], frame["b"], frame["v"]))
        return self._cached(s, "network", build)

    def _shipped_totals(self, s: Session) -> dict[str, int]:
        def build() -> dict[str, int]:
            frame = s.q(SHIPPED_TOTALS_Q)
            return {str(f): int(n) for f, n in zip(frame["fid"], frame["n"])}
        return self._cached(s, "shipped_totals", build)

    def facility_index(self, s: Session) -> FacilityIndex:
        def build() -> FacilityIndex:
            frame = s.q(f"MATCH (n:Facility) RETURN n, n.facility_id AS fid{s.project('n', NODE_PROPS)}")
            nodes = {n.id: n for n in s.nodes_from(frame, "n", label="Facility")}
            by_fid: dict[str, Node] = {}
            fid_by_id: dict[str, str] = {}
            for nid, fid in zip(frame["n"], frame["fid"]):
                node = nodes[str(nid)]
                by_fid[str(fid)] = node
                fid_by_id[node.id] = str(fid)
            platforms: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
            if "Platform" in s.labels:
                p = s.q(PLATFORMS_Q)
                for fid, name, archetype in zip(p["fid"], p["name"], p["archetype"]):
                    platforms[str(fid)].append((str(name), clean(archetype)))
            return FacilityIndex(by_fid, fid_by_id, {k: tuple(v) for k, v in platforms.items()})
        return self._cached(s, "facility_index", build)

    def catalog(self, s: Session) -> list[tuple[Node, OriginKind]]:
        def build() -> list[tuple[Node, OriginKind]]:
            out: list[tuple[Node, OriginKind]] = []
            for label in ("Chokepoint", "Port"):
                if label in s.labels:
                    frame = s.q(f"MATCH (n:{label}) RETURN n{s.project('n', NODE_PROPS)}")
                    out += [(n, ORIGIN_LABELS[label]) for n in s.nodes_from(frame, "n", label=label)]
            out += [(n, "facility") for n in self.facility_index(s).by_fid.values()]
            return out
        return self._cached(s, "catalog", build)

    # ------------------------------------------------------------------ origin + seeds

    def origin(self, s: Session, origin_id: str) -> Origin:
        nid = node_id_literal(origin_id)
        props = NODE_PROPS + tuple(KEY_PROP.values())
        frame = s.q(f"MATCH (n) WHERE n = {nid} RETURN n, labels(n) AS lbl{s.project('n', props)}")
        if frame.empty:
            raise NotFound(f"node {origin_id} not on {s.ref}")
        node = s.nodes_from(frame, "n", label_col="lbl")[0]
        kind = ORIGIN_LABELS.get(node.label)
        if kind is None:
            raise ValueError(f"a {node.label} cannot be a cascade origin: pick a chokepoint, port or facility")
        if not is_located(node):
            raise ValueError(f"{node.name} has no coordinates")
        key = clean(frame.iloc[0].get(f"n_{KEY_PROP[kind]}"))
        if key is None:
            raise ValueError(f"{node.name} has no {KEY_PROP[kind]}")
        return Origin(node=with_status(node, "lost"), kind=kind, key=str(key))

    @staticmethod
    def _origin_pattern(origin: Origin) -> str:
        return f"(o:{LABEL_OF[origin.kind]} {{{KEY_PROP[origin.kind]}: {string_literal(origin.key)}}})"

    def seeds(self, s: Session, origin: Origin) -> Seeds:
        if origin.kind == "facility":
            return Seeds({origin.key: 1.0}, degree=0, via="SUPPLIES")
        edge = SEED_EDGE[origin.kind]
        frame = s.q(f"MATCH {self._origin_pattern(origin)}<-[:{edge}]-(c:Consignment)-[:SHIPPED_FROM]->(f:Facility) "
                    "RETURN f.facility_id AS fid, count(DISTINCT c) AS n")
        return Seeds(_shares(frame, self._shipped_totals(s)), degree=1, via=edge)

    def seeds_by_origin(self, s: Session, kind: Literal["chokepoint", "port"]) -> dict[str, Seeds]:
        edge, label = SEED_EDGE[kind], LABEL_OF[kind]
        frame = s.q(f"MATCH (o:{label})<-[:{edge}]-(c:Consignment)-[:SHIPPED_FROM]->(f:Facility) "
                    "RETURN o, f.facility_id AS fid, count(DISTINCT c) AS n")
        totals = self._shipped_totals(s)
        frame = frame.assign(o=frame["o"].astype(str))
        return {str(oid): Seeds(_shares(group, totals), degree=1, via=edge) for oid, group in frame.groupby("o")}

    # ------------------------------------------------------------------ the speed proof

    def reach(self, s: Session, origin: Origin) -> ReachProbe:
        """One deep variable-length query, timed by TuringDB itself: unweighted reach up to MAX_DEGREE hops."""
        span = f"-[:SUPPLIES]->{{1,{MAX_DEGREE}}}(g:Facility)"
        if origin.kind == "facility":
            cypher = f"MATCH {self._origin_pattern(origin)}{span} RETURN count(DISTINCT g) AS reached"
        else:
            cypher = (f"MATCH {self._origin_pattern(origin)}<-[:{SEED_EDGE[origin.kind]}]-(c:Consignment)"
                      f"-[:SHIPPED_FROM]->(f:Facility){span} RETURN count(DISTINCT g) AS reached")
        frame = s.q(cypher)
        reached = int(frame["reached"].iloc[0]) if len(frame) else 0
        return ReachProbe(cypher=cypher, depth_limit=MAX_DEGREE, reached=reached, ms=s.sw.traces[-1].ms)

    # ------------------------------------------------------------------ the response

    def compute(self, ref: Ref, origin_id: str, min_severity: float = MIN_SEVERITY) -> CascadeResponse:
        sw = Stopwatch(ENGINE)
        s = self.session(ref, sw)
        origin = self.origin(s, origin_id)
        probe = self.reach(s, origin)
        layers = propagate(self.seeds(s, origin), self.network(s), min_severity)
        index = self.facility_index(s)
        stages = build_stages(origin, layers, index)
        hops = len(stages) + (1 if origin.kind != "facility" and stages else 0)
        return CascadeResponse(branch=str(ref), origin=origin.node, origin_kind=origin.kind, min_severity=min_severity,
                               stages=stages, max_degree=len(stages), graph_hops=hops,
                               total_affected=sum(st.count for st in stages), reach=probe,
                               platforms=platform_exposure(origin, layers, index), **sw.timed())
```

Notes for the implementer:
- `ENGINE` must be importable from `api.backends.turing` (it is used there). If it is defined elsewhere,
  import it from there.
- `s.sw` is the `Stopwatch` given to `Session(...)`. Check the attribute name in `turing_session.py`
  (`self.ref, self.sw = ref, sw`); it is `sw`.
- `frame.iloc[0].get("n_waypoint_id")`: `Session.project` only adds columns for properties that exist in the
  graph (`has_props`), so a missing column returns `None` and the origin is rejected with a clear message.
- If TuringDB rejects the grouped `RETURN o, f.facility_id, count(DISTINCT c)` query, fall back to one
  `seeds()` call per chokepoint/port from `catalog()`. Keep the same return type and note it in the commit
  message. Research showed grouped `count(DISTINCT …)` by facility works.

- [ ] **Step 6: Run the live tests**

Run: `uv run pytest tests/api/test_deep_cascade_live.py -q`
Expected: all pass. If `stages[0].count == 8` fails, run this fresh direct query:
`MATCH (k:Chokepoint {name:'Strait of Hormuz'})<-[:TRANSITED]-(c:Consignment)-[:SHIPPED_FROM]->(f:Facility) RETURN count(DISTINCT f)`.
Then use its count minus the facilities below 5% severity, and document the change.

- [ ] **Step 7: Run the whole API suite (regression)**

Run: `uv run pytest tests/api -q`
Expected: all pass. `test_turing_live.py` must still pass: `SNAPSHOT_KINDS` now includes chokepoints, so a
diff on main→main must still be empty.

- [ ] **Step 8: Commit**

```bash
git add api/deep_cascade_live.py api/backends/turing.py tests/api/test_deep_cascade_live.py
git commit -m "feat: live deep cascade over TuringDB with timed 12-hop reach query

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A3: Place-name resolution

**Files:**
- Create: `api/cascade_resolve.py`
- Test: `tests/api/test_cascade_resolve.py`

**Interfaces:**
- Consumes: `api.models.{Node, OriginCandidate, OriginKind}`.
- Produces: `normalize(text: str) -> str`; `resolve(question: str, catalog: Sequence[tuple[Node, OriginKind]],
  limit: int = 8) -> list[OriginCandidate]`; `pick(candidates: Sequence[OriginCandidate]) -> OriginCandidate | None`;
  constants `CONFIDENT = 0.8`, `MARGIN = 0.15`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_cascade_resolve.py`:

```python
"""Question -> cascade origin. Deterministic, no LLM: an alias table plus name-token matching."""

from __future__ import annotations

from api.cascade_resolve import normalize, pick, resolve
from api.nodes import make_node

CATALOG = [
    (make_node(1, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4}), "chokepoint"),
    (make_node(2, "Chokepoint", {"name": "Taiwan Strait", "latitude": 24.0, "longitude": 119.5}), "chokepoint"),
    (make_node(3, "Chokepoint", {"name": "Bab-el-Mandeb", "latitude": 12.6, "longitude": 43.3}), "chokepoint"),
    (make_node(4, "Port", {"name": "Port of Busan", "latitude": 35.1, "longitude": 129.0}), "port"),
    (make_node(5, "Port", {"name": "Port of Hamburg", "latitude": 53.5, "longitude": 9.9}), "port"),
    (make_node(6, "Port", {"name": "Port of Bandar Abbas", "latitude": 27.1, "longitude": 56.2}), "port"),
    (make_node(7, "Facility", {"name": "Meridian Mining FZE - Dubai", "latitude": 25.2, "longitude": 55.3}), "facility"),
]


def names(cands):
    return [c.node.name for c in cands]


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize("What if the Strait of HORMUZ closes?") == "what if the strait of hormuz closes"
    assert normalize("Bab-el-Mandeb") == "bab el mandeb"


def test_alias_resolves_hormuz_confidently():
    cands = resolve("Hormuz is blocked. What happens now?", CATALOG)
    assert names(cands)[0] == "Strait of Hormuz" and cands[0].score == 1.0
    assert pick(cands).node.name == "Strait of Hormuz"


def test_full_name_and_short_name():
    assert pick(resolve("What if the Strait of Hormuz closes?", CATALOG)).node.name == "Strait of Hormuz"
    assert pick(resolve("taiwan blockade", CATALOG)).node.name == "Taiwan Strait"
    assert pick(resolve("What if the Red Sea closes?", CATALOG)).node.name == "Bab-el-Mandeb"


def test_port_by_city_word():
    assert pick(resolve("Busan shuts down", CATALOG)).node.name == "Port of Busan"


def test_facility_by_name_tokens():
    assert pick(resolve("Meridian Dubai goes down", CATALOG)).node.name == "Meridian Mining FZE - Dubai"


def test_pick_requires_margin():
    cands = resolve("Busan and Hamburg ports close", CATALOG)
    assert {"Port of Busan", "Port of Hamburg"} <= set(names(cands))
    assert pick(cands) is None


def test_unknown_place_gives_no_candidates():
    assert resolve("what happens tomorrow?", CATALOG) == []
    assert pick([]) is None


def test_stop_words_alone_do_not_match():
    assert resolve("the port of the strait", CATALOG) == []


def test_limit_and_kind_priority():
    cands = resolve("bandar abbas hormuz", CATALOG, limit=2)
    assert len(cands) == 2 and cands[0].origin_kind == "chokepoint"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_cascade_resolve.py -q`
Expected: `ModuleNotFoundError: No module named 'api.cascade_resolve'`.

- [ ] **Step 3: Implement**

Create `api/cascade_resolve.py`:

```python
"""Resolve a plain-language question ("What happens if the Strait of Hormuz closes?") to a cascade origin,
without an LLM.

Deterministic on purpose: the demo must never depend on a model being warm. Short aliases cover the 15
chokepoints ("hormuz", "red sea", "bosphorus"); ports and facilities match on their distinctive name words.
Ambiguity is returned to the operator as candidates rather than guessed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from api.models import Node, OriginCandidate, OriginKind

CONFIDENT = 0.8
MARGIN = 0.15
MIN_TOKEN = 4
KIND_ORDER: dict[str, int] = {"chokepoint": 0, "port": 1, "facility": 2}
STOP = frozenset({"port", "of", "the", "strait", "straits", "canal", "sea", "co", "ltd", "inc", "jsc", "fze", "llc",
                  "gmbh", "sa", "ag", "plc", "corp", "group", "mining", "materials", "components", "trading"})

# normalized alias phrase -> canonical chokepoint name (as stored in the graph)
ALIASES: dict[str, str] = {
    "hormuz": "Strait of Hormuz",
    "taiwan": "Taiwan Strait",
    "malacca": "Strait of Malacca",
    "bab el mandeb": "Bab-el-Mandeb", "red sea": "Bab-el-Mandeb",
    "suez": "Suez Canal",
    "panama": "Panama Canal",
    "gibraltar": "Strait of Gibraltar",
    "turkish straits": "Turkish Straits", "bosphorus": "Turkish Straits", "dardanelles": "Turkish Straits",
    "danish straits": "Danish Straits",
    "dover": "Dover Strait", "english channel": "Dover Strait",
    "korea strait": "Korea Strait",
    "luzon": "Luzon Strait", "sunda": "Sunda Strait", "lombok": "Lombok Strait", "florida": "Florida Strait",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _has_phrase(haystack: str, phrase: str) -> bool:
    return f" {phrase} " in f" {haystack} "


def _tokens(name: str) -> set[str]:
    return {t for t in normalize(name).split() if t not in STOP and len(t) >= MIN_TOKEN}


def _score(q: str, words: set[str], node: Node, kind: OriginKind, aliased: set[str]) -> float:
    if node.name in aliased:
        return 1.0
    if _has_phrase(q, normalize(node.name)):
        return 0.95
    tokens = _tokens(node.name)
    found = tokens & words
    if not found:
        return 0.0
    if found == tokens:
        return 0.85 if kind != "facility" else 0.8
    return 0.5 if kind != "facility" else 0.3


def resolve(question: str, catalog: Sequence[tuple[Node, OriginKind]], limit: int = 8) -> list[OriginCandidate]:
    q = normalize(question)
    words = set(q.split())
    aliased = {name for phrase, name in ALIASES.items() if _has_phrase(q, phrase)}
    scored = [(_score(q, words, node, kind, aliased), node, kind) for node, kind in catalog]
    hits = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], KIND_ORDER[x[2]], x[1].name))
    return [OriginCandidate(node=node, origin_kind=kind, score=round(score, 3)) for score, node, kind in hits[:limit]]


def pick(candidates: Sequence[OriginCandidate]) -> OriginCandidate | None:
    """The single confident origin, or None when the operator should choose."""
    if not candidates or candidates[0].score < CONFIDENT:
        return None
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < MARGIN:
        return None
    return candidates[0]
```

Expected scores (use them to debug): "Meridian Dubai goes down" → facility tokens {meridian, dubai} all found
→ 0.8, nobody else > 0 → picked. "bandar abbas hormuz" → Hormuz 1.0 (alias), Bandar Abbas 0.85 → top is the
chokepoint. "Busan and Hamburg ports close" → Busan 0.85, Hamburg 0.85, margin 0 → `None`. If a test
disagrees with these numbers, fix the code, not the test.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_cascade_resolve.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/cascade_resolve.py tests/api/test_cascade_resolve.py
git commit -m "feat: resolve plain-language place questions to cascade origins

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A4: HTTP routes `/cascade/*`

**Files:**
- Create: `api/cascade_routes.py`
- Modify: `api/main.py`
- Test: `tests/api/test_cascade_routes.py`

**Interfaces:**
- Consumes: `DeepCascade` (A2), `resolve`/`pick` (A3), `api.refs.parse_ref`, models (A1).
- Produces: `register_cascade_routes(app: FastAPI, engine_factory: Callable[[FastAPI], CascadeEngine] | None = None) -> None`
  and the `CascadeEngine` Protocol (`session`, `catalog`, `compute`), so tests inject a fake.

- [ ] **Step 1: Write the failing route tests**

Create `tests/api/test_cascade_routes.py`:

```python
"""/cascade routes with a fake engine (no TuringDB). The live engine is covered by test_deep_cascade_live.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.cascade_routes import register_cascade_routes
from api.main import create_app
from api.models import CascadeResponse, ReachProbe
from api.nodes import make_node, with_status
from api.support import NotFound

HORMUZ = make_node(11, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4})
BUSAN = make_node(12, "Port", {"name": "Port of Busan", "latitude": 35.1, "longitude": 129.0})
HAMBURG = make_node(13, "Port", {"name": "Port of Hamburg", "latitude": 53.5, "longitude": 9.9})


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def session(self, ref, sw=None):
        return ref

    def catalog(self, s):
        return [(HORMUZ, "chokepoint"), (BUSAN, "port"), (HAMBURG, "port")]

    def compute(self, ref, origin_id, min_severity=0.05):
        self.calls.append((str(ref), origin_id, min_severity))
        if origin_id == "404":
            raise NotFound("node 404 not on main")
        return CascadeResponse(engine="turingdb", latency_ms=1.0, roundtrip_ms=2.0, branch=str(ref),
                               origin=with_status(HORMUZ, "lost"), origin_kind="chokepoint", min_severity=min_severity,
                               stages=[], max_degree=0, graph_hops=0, total_affected=0,
                               reach=ReachProbe(cypher="MATCH ...", depth_limit=12, reached=0, ms=1.0), platforms=[])


@pytest.fixture
def fake() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def cclient(backend, fake):
    app = create_app(backend)
    register_cascade_routes(app, engine_factory=lambda _app: fake)
    with TestClient(app) as c:
        yield c


def test_routes_absent_on_mock_backend_without_registration(client):
    assert client.post("/cascade", json={"origin_id": "1"}).status_code == 404


def test_origins_lists_ranked_candidates(cclient):
    body = cclient.get("/cascade/origins", params={"q": "hormuz"}).json()
    assert body["query"] == "hormuz" and body["candidates"][0]["node"]["name"] == "Strait of Hormuz"
    assert body["candidates"][0]["origin_kind"] == "chokepoint"


def test_origins_rejects_too_short_query(cclient):
    assert cclient.get("/cascade/origins", params={"q": "h"}).status_code == 422


def test_cascade_by_id_passes_branch_and_threshold(cclient, fake):
    r = cclient.post("/cascade", json={"origin_id": "11", "branch": "main", "min_severity": 0.1})
    assert r.status_code == 200 and r.json()["origin"]["status"] == "lost"
    assert [(c[1], c[2]) for c in fake.calls] == [("11", 0.1)]


def test_cascade_validates_threshold(cclient):
    assert cclient.post("/cascade", json={"origin_id": "11", "min_severity": 0.9}).status_code == 422


def test_cascade_unknown_origin_is_404(cclient):
    assert cclient.post("/cascade", json={"origin_id": "404"}).status_code == 404


def test_ask_resolves_plain_question(cclient, fake):
    r = cclient.post("/cascade/ask", json={"question": "What happens if the Strait of Hormuz closes?"})
    assert r.status_code == 200 and fake.calls[-1][1] == "11"


def test_ask_ambiguous_is_422_with_candidates(cclient):
    r = cclient.post("/cascade/ask", json={"question": "Busan and Hamburg close"})
    body = r.json()
    assert r.status_code == 422 and len(body["candidates"]) >= 2 and "choose" in body["detail"].lower()


def test_ask_unknown_place_is_422_with_candidates(cclient):
    r = cclient.post("/cascade/ask", json={"question": "what happens tomorrow?"})
    assert r.status_code == 422 and r.json()["candidates"] == []
```

(`backend` and `client` are fixtures in `tests/api/conftest.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_cascade_routes.py -q`
Expected: `ModuleNotFoundError: No module named 'api.cascade_routes'`.

- [ ] **Step 3: Implement the routes**

Create `api/cascade_routes.py`:

```python
"""OpsMap routes for the deep-supply impact cascade (read-only; never creates a branch).

    GET  /cascade/origins?q=     place search (chokepoints, ports, facilities) with short aliases
    POST /cascade                {origin_id, branch, min_severity} -> per-degree CascadeResponse
    POST /cascade/ask            {question, branch, min_severity} -> same, or 422 {detail, candidates}

Mounted only on the live TuringDB backend. Contract: docs/api.md "Impact cascade".
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, Sequence

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from api.cascade_resolve import pick, resolve
from api.models import CascadeAskRequest, CascadeRequest, CascadeResponse, Node, OriginKind, OriginsResponse
from api.refs import Ref, parse_ref

log = logging.getLogger("opsmap.cascade")
MAX_CANDIDATES = 8


class CascadeEngine(Protocol):
    def session(self, ref: Ref, sw: Any = None) -> Any: ...
    def catalog(self, s: Any) -> Sequence[tuple[Node, OriginKind]]: ...
    def compute(self, ref: Ref, origin_id: str, min_severity: float = ...) -> CascadeResponse: ...


def _default_engine(app: FastAPI) -> CascadeEngine:
    from api.deep_cascade_live import DeepCascade

    return DeepCascade(app.state.backend)


def register_cascade_routes(app: FastAPI,
                            engine_factory: Callable[[FastAPI], CascadeEngine] | None = None) -> None:
    holder: dict[str, CascadeEngine] = {}

    def engine() -> CascadeEngine:
        if "engine" not in holder:
            holder["engine"] = (engine_factory or _default_engine)(app)
        return holder["engine"]

    def catalog(branch: str) -> Sequence[tuple[Node, OriginKind]]:
        eng = engine()
        return eng.catalog(eng.session(parse_ref(branch)))

    @app.get("/cascade/origins", response_model=OriginsResponse, response_model_exclude_none=True)
    def origins(q: str = Query(min_length=2, max_length=120), branch: str = "main"):
        return OriginsResponse(query=q, candidates=resolve(q, catalog(branch), MAX_CANDIDATES))

    @app.post("/cascade", response_model=CascadeResponse, response_model_exclude_none=True)
    def cascade(req: CascadeRequest):
        return engine().compute(parse_ref(req.branch), req.origin_id, req.min_severity)

    @app.post("/cascade/ask", response_model=CascadeResponse, response_model_exclude_none=True)
    def ask(req: CascadeAskRequest):
        candidates = resolve(req.question, catalog(req.branch), MAX_CANDIDATES)
        chosen = pick(candidates)
        if chosen is None:
            detail = ("No chokepoint, port or facility recognised in the question" if not candidates
                      else "Several places match: choose one")
            return JSONResponse(status_code=422, content={
                "detail": detail,
                "candidates": [c.model_dump(mode="json", exclude_none=True) for c in candidates],
            })
        log.info("cascade ask %r -> %s", req.question, chosen.node.name)
        return engine().compute(parse_ref(req.branch), chosen.node.id, req.min_severity)
```

In `api/main.py`, inside the existing `if settings.backend == "turingdb":` block, after the agent routes'
`try/except`, add a second independent block:

```python
        try:
            from api.cascade_routes import register_cascade_routes

            register_cascade_routes(app)
        except Exception as exc:  # never let cascade wiring break the core API
            log.warning("cascade routes not mounted: %s", exc)
```

- [ ] **Step 4: Run route tests and the whole API suite**

Run: `uv run pytest tests/api -q`
Expected: all pass.

- [ ] **Step 5: Smoke-test against the live API**

Start the API with the Bash tool's `run_in_background`:
`OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app --port 8000`. If port 8000 is busy, do not kill someone
else's process (`lsof -ti :8000` shows it); use `--port 8020` instead. Then:

```bash
curl -s "localhost:8000/cascade/origins?q=h%C3%BCrm%C3%BCz" | python -m json.tool | head -20
```

```bash
curl -s -X POST localhost:8000/cascade/ask -H 'Content-Type: application/json' -d '{"question":"What happens if the Strait of Hormuz closes?"}' | python -c "import sys,json;r=json.load(sys.stdin);print(r['origin']['name'],r['max_degree'],r['graph_hops'],[s['count'] for s in r['stages']],r['reach']['ms'],r['latency_ms'])"
```
Expected: `Strait of Hormuz 7 8 [8, 18, ...] <small ms> <ms>`.

- [ ] **Step 6: Commit**

```bash
git add api/cascade_routes.py api/main.py tests/api/test_cascade_routes.py
git commit -m "feat: /cascade routes (origins, by id, natural-language ask)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A5: UI types, client and pure cascade helpers

**Files:**
- Modify: `ui/src/api/types.ts`, `ui/src/api/client.ts`, `ui/src/map/colors.ts`
- Create: `ui/src/lib/cascade.ts`
- Test: `ui/src/lib/cascade.test.ts`

**Interfaces:**
- Consumes: response shapes (A1), `RGBA` from `ui/src/map/colors.ts` (exported).
- Produces (TS): `OriginKind`, `CascadeHit`, `CascadeStage`, `ReachProbe`, `PlatformExposure`, `OriginCandidate`,
  `OriginsResponse`, `CascadeResponse`, `CascadeRequest`, `CascadeAskRequest`; `api.cascadeOrigins(q, branch?)`,
  `api.cascade(req)`, `api.cascadeAsk(req)`; `ApiError.body: unknown`;
  `lib/cascade.ts`: `DEGREE_COLORS`, `degreeColor`, `degreeCss`, `ordinal`, `clampStep`, `visibleStages`,
  `currentStage`, `topHits`, `stepLabel`, `headline`, `cascadeFocus`, `MAX_LABELS_PER_DEGREE`.

- [ ] **Step 1: Write the failing helper tests**

Create `ui/src/lib/cascade.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { CascadeHit, CascadeResponse, CascadeStage, GraphNode } from "../api/types";
import {
  DEGREE_COLORS,
  MAX_LABELS_PER_DEGREE,
  cascadeFocus,
  clampStep,
  currentStage,
  degreeColor,
  degreeCss,
  headline,
  ordinal,
  stepLabel,
  topHits,
  visibleStages,
} from "./cascade";

const node = (id: string, lon: number, lat: number, kind: GraphNode["kind"] = "facility"): GraphNode => ({
  id, kind, label: kind === "facility" ? "Facility" : "Chokepoint", name: `N${id}`, lon, lat, importance: 0.5,
});

const hit = (id: string, degree: number, severity: number, lon = 10, lat = 50): CascadeHit => ({
  node: node(id, lon, lat), degree, severity, parent_id: "0", via: degree === 1 ? "TRANSITED" : "SUPPLIES",
});

const stage = (degree: number, hits: CascadeHit[]): CascadeStage => ({
  degree, hits, arcs: [], count: hits.length,
  mean_severity: hits.reduce((a, h) => a + h.severity, 0) / Math.max(1, hits.length),
});

const result = (stages: CascadeStage[]): CascadeResponse => ({
  engine: "turingdb", latency_ms: 23.4, roundtrip_ms: 80, queries: [{ cypher: "q", ms: 8 }, { cypher: "r", ms: 15.4 }],
  branch: "main", origin: { ...node("0", 56.4, 26.5, "chokepoint"), name: "Strait of Hormuz", status: "lost" },
  origin_kind: "chokepoint", min_severity: 0.05, stages, max_degree: stages.length,
  graph_hops: stages.length ? stages.length + 1 : 0,
  total_affected: stages.reduce((a, s) => a + s.count, 0),
  reach: { cypher: "MATCH ...{1,12}...", depth_limit: 12, reached: 2262, ms: 8.2 }, platforms: [],
});

const hormuz = result([
  stage(1, [hit("a", 1, 1), hit("b", 1, 0.5, 20, 40)]),
  stage(2, [hit("c", 2, 0.4, 30, 30)]),
  stage(3, [hit("d", 3, 0.1, 40, 20)]),
]);

describe("degree colours and ordinals", () => {
  it("gives a distinct colour per degree and clamps beyond the palette", () => {
    expect(new Set(DEGREE_COLORS.map((c) => c.join())).size).toBe(DEGREE_COLORS.length);
    expect(degreeColor(1)).toEqual(DEGREE_COLORS[0]);
    expect(degreeColor(99)).toEqual(DEGREE_COLORS[DEGREE_COLORS.length - 1]);
    expect(degreeColor(0)).toEqual(DEGREE_COLORS[0]);
    expect(degreeCss(1)).toBe(`rgb(${DEGREE_COLORS[0].slice(0, 3).join(" ")})`);
  });
  it("formats English ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]);
  });
});

describe("stepping", () => {
  it("clamps the step to 0..max_degree", () => {
    expect(clampStep(-1, hormuz)).toBe(0);
    expect(clampStep(2, hormuz)).toBe(2);
    expect(clampStep(9, hormuz)).toBe(3);
  });
  it("reveals degrees up to the step", () => {
    expect(visibleStages(hormuz, 0)).toEqual([]);
    expect(visibleStages(hormuz, 2).map((s) => s.degree)).toEqual([1, 2]);
    expect(currentStage(hormuz, 0)).toBeNull();
    expect(currentStage(hormuz, 2)?.degree).toBe(2);
  });
  it("labels each step", () => {
    expect(stepLabel(hormuz, 0)).toBe("Strait of Hormuz closed. Impact reaches 3 degrees: press Continue for the 1st degree.");
    expect(stepLabel(hormuz, 1)).toBe("1st degree of 3: 2 facilities lose supply (mean 75% of inbound volume).");
    expect(stepLabel(hormuz, 3)).toBe("3rd degree of 3: 1 facility loses supply (mean 10% of inbound volume). End of the cascade.");
    expect(stepLabel(result([]), 0)).toBe("Strait of Hormuz closed. No facility loses at least 5% of its supply.");
  });
});

describe("headline", () => {
  it("summarises TuringDB speed and depth", () => {
    expect(headline(hormuz)).toEqual({
      degrees: 3, hops: 4, affected: 4, reached: 2262, reachMs: 8.2, totalMs: 23.4, queries: 2, depthLimit: 12,
    });
  });
});

describe("topHits", () => {
  it("returns the highest-severity hits, capped", () => {
    const many = stage(1, Array.from({ length: 30 }, (_, i) => hit(`h${i}`, 1, 1 - i / 100)));
    expect(topHits(many).length).toBe(MAX_LABELS_PER_DEGREE);
    expect(topHits(many, 3).map((h) => h.node.id)).toEqual(["h0", "h1", "h2"]);
  });
});

describe("cascadeFocus", () => {
  it("centres on the origin at step 0 and on the revealed stage afterwards", () => {
    expect(cascadeFocus(hormuz, 0)).toEqual({ lon: 56.4, lat: 26.5, zoom: 4 });
    const f = cascadeFocus(hormuz, 1);
    expect(f.lon).toBeCloseTo(15);
    expect(f.lat).toBeCloseTo(45);
    expect(f.zoom).toBeGreaterThanOrEqual(1.8);
    expect(f.zoom).toBeLessThanOrEqual(6);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm --prefix ui test -- --run src/lib/cascade.test.ts`
Expected: FAIL — cannot resolve `./cascade`, and the types are missing.

- [ ] **Step 3: Add types and client calls**

In `ui/src/api/types.ts`, add `| "chokepoint"` to `Kind` (before `"other"`) and append:

```ts
// ---------------------------------------------------------------- impact cascade (docs/api.md)

export type OriginKind = "chokepoint" | "port" | "facility";

export interface CascadeHit {
  node: GraphNode;
  degree: number;
  severity: number;
  parent_id?: string | null;
  via: string;
}

export interface CascadeStage {
  degree: number;
  hits: CascadeHit[];
  arcs: Arc[];
  count: number;
  mean_severity: number;
}

export interface ReachProbe {
  cypher: string;
  depth_limit: number;
  reached: number;
  ms?: number | null;
}

export interface PlatformExposure {
  name: string;
  archetype?: string | null;
  severity: number;
  facility_id: string;
}

export interface CascadeResponse extends Timed {
  branch: string;
  origin: GraphNode;
  origin_kind: OriginKind;
  min_severity: number;
  stages: CascadeStage[];
  max_degree: number;
  graph_hops: number;
  total_affected: number;
  reach: ReachProbe;
  platforms: PlatformExposure[];
}

export interface CascadeRequest {
  origin_id: string;
  branch?: string;
  min_severity?: number;
}

export interface CascadeAskRequest {
  question: string;
  branch?: string;
  min_severity?: number;
}

export interface OriginCandidate {
  node: GraphNode;
  origin_kind: OriginKind;
  score: number;
}

export interface OriginsResponse {
  query: string;
  candidates: OriginCandidate[];
}
```

Check that `Timed` exists in `types.ts` (`grep -n "interface Timed" ui/src/api/types.ts`); if it has another
name, extend that one.

In `ui/src/api/client.ts`, give `ApiError` a `body` field. Keep its existing members and only add the
third constructor parameter:

```ts
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly body: unknown = null) {
    super(message);
    this.name = "ApiError";
  }
}
```

In `request()`, keep the parsed body:

```ts
  if (!resp.ok) {
    let detail = resp.statusText;
    let body: unknown = null;
    try {
      body = await resp.json();
      const d = (body as { detail?: unknown }).detail;
      if (typeof d === "string") detail = d;
    } catch {
      // non-JSON error body: keep the status text
    }
    throw new ApiError(detail || `HTTP ${resp.status}`, resp.status, body);
  }
```

Add to `api` (and import the new types):

```ts
  cascadeOrigins: (q: string, branch = "main") =>
    request<OriginsResponse>(`/cascade/origins${queryString({ q, branch })}`),
  cascade: (req: CascadeRequest) => request<CascadeResponse>("/cascade", { method: "POST", body: JSON.stringify(req) }),
  cascadeAsk: (req: CascadeAskRequest) =>
    request<CascadeResponse>("/cascade/ask", { method: "POST", body: JSON.stringify(req) }),
```

In `ui/src/map/colors.ts`, add `chokepoint: [120, 200, 255, 255],` to `NEUTRAL` (TypeScript requires every
`Kind`).

- [ ] **Step 4: Implement `ui/src/lib/cascade.ts`**

```ts
// Pure helpers for the step-by-step impact cascade: one colour per degree (same on the map, in the ladder
// and in the vulnerability tree), step clamping, the operator-facing labels and the map focus per step.

import type { CascadeHit, CascadeResponse, CascadeStage } from "../api/types";
import type { RGBA } from "../map/colors";

export const MAX_LABELS_PER_DEGREE = 8;
const ORIGIN_ZOOM = 4;
const MIN_ZOOM = 1.8;
const MAX_ZOOM = 6;

/** Hot (degree 1, nearest the shock) to cool (far tail). Distinct hues so "which degree" reads at a glance. */
export const DEGREE_COLORS: RGBA[] = [
  [235, 72, 76, 255],
  [244, 114, 54, 255],
  [245, 166, 35, 255],
  [236, 204, 58, 255],
  [163, 207, 72, 255],
  [74, 196, 140, 255],
  [56, 189, 212, 255],
  [61, 139, 240, 255],
  [124, 110, 240, 255],
  [178, 98, 226, 255],
  [214, 92, 184, 255],
  [190, 200, 214, 255],
];

export function degreeColor(degree: number): RGBA {
  const i = Math.min(DEGREE_COLORS.length - 1, Math.max(0, degree - 1));
  return DEGREE_COLORS[i];
}

export function degreeCss(degree: number): string {
  const [r, g, b] = degreeColor(degree);
  return `rgb(${r} ${g} ${b})`;
}

export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  const suffix = ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

export function clampStep(step: number, result: CascadeResponse): number {
  return Math.min(result.max_degree, Math.max(0, Math.round(step)));
}

export function visibleStages(result: CascadeResponse, step: number): CascadeStage[] {
  return result.stages.slice(0, clampStep(step, result));
}

export function currentStage(result: CascadeResponse, step: number): CascadeStage | null {
  const s = clampStep(step, result);
  return s > 0 ? result.stages[s - 1] ?? null : null;
}

export function topHits(stage: CascadeStage, n = MAX_LABELS_PER_DEGREE): CascadeHit[] {
  return stage.hits.slice(0, n); // the server sorts hits by severity, highest first
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function stepLabel(result: CascadeResponse, step: number): string {
  const name = result.origin.name;
  const s = clampStep(step, result);
  if (!result.max_degree) return `${name} closed. No facility loses at least ${pct(result.min_severity)} of its supply.`;
  if (s === 0) return `${name} closed. Impact reaches ${result.max_degree} degrees: press Continue for the 1st degree.`;
  const st = result.stages[s - 1];
  const noun = st.count === 1 ? "facility loses" : "facilities lose";
  const end = s === result.max_degree ? " End of the cascade." : "";
  return `${ordinal(s)} degree of ${result.max_degree}: ${st.count.toLocaleString("en-GB")} ${noun} supply (mean ${pct(st.mean_severity)} of inbound volume).${end}`;
}

export interface Headline {
  degrees: number;
  hops: number;
  affected: number;
  reached: number;
  reachMs: number | null;
  totalMs: number;
  queries: number;
  depthLimit: number;
}

export function headline(r: CascadeResponse): Headline {
  return {
    degrees: r.max_degree,
    hops: r.graph_hops,
    affected: r.total_affected,
    reached: r.reach.reached,
    reachMs: r.reach.ms ?? null,
    totalMs: r.latency_ms,
    queries: r.queries?.length ?? 0,
    depthLimit: r.reach.depth_limit,
  };
}

export interface Focus {
  lon: number;
  lat: number;
  zoom: number;
}

export function cascadeFocus(result: CascadeResponse, step: number): Focus {
  const st = currentStage(result, step);
  const pts = (st?.hits ?? []).map((h) => h.node).filter((n) => n.lon != null && n.lat != null);
  if (!pts.length) return { lon: result.origin.lon ?? 0, lat: result.origin.lat ?? 0, zoom: ORIGIN_ZOOM };
  const lons = pts.map((n) => n.lon as number);
  const lats = pts.map((n) => n.lat as number);
  const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats), 1);
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.log2(360 / span) - 0.5));
  return { lon: lons.reduce((a, b) => a + b, 0) / lons.length, lat: lats.reduce((a, b) => a + b, 0) / lats.length, zoom };
}
```

- [ ] **Step 5: Run the UI tests and the typecheck**

Run: `npm --prefix ui test -- --run src/lib/cascade.test.ts && npm --prefix ui run typecheck`
Expected: tests pass. The typecheck may fail elsewhere because `Kind` gained `chokepoint`. Fix only the
exhaustive records or switches the compiler names (e.g. `NEUTRAL`, glyph maps) by adding a chokepoint entry.
Do not weaken types.

- [ ] **Step 6: Commit**

```bash
git add ui/src/api/types.ts ui/src/api/client.ts ui/src/map/colors.ts ui/src/lib/cascade.ts ui/src/lib/cascade.test.ts
git commit -m "feat(ui): cascade types, client calls and step helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A6: Cascade state, stepper and Impact panel

**Files:**
- Modify: `ui/src/state/store.ts`, `ui/src/components/BottomBar.tsx`, `ui/src/components/ContextMenu.tsx`,
  `ui/src/styles/app.css`
- Create: `ui/src/state/cascade.ts`, `ui/src/components/CascadeStepper.tsx`, `ui/src/components/CascadePanel.tsx`

**Interfaces:**
- Consumes: A5 client + helpers; existing `setOps`, `useOps`, `toast`, `message`, `recordLatency`, `flyToNode`
  (`state/actions.ts`), `ScenarioPrompt`, `ApiError`.
- Produces: contract § Cross-boundary UI interface (`CascadeState`, `CascadeSource`, `showCascade`,
  `cascadeNext`, `cascadePrev`, `cascadeShowAll`, `cascadeReset`, `clearCascade`, `<CascadeStepper />`), plus
  `setCascadeOpen(open)`, `setCascadeQuestion(q)`, `askCascade()`, `runCascadeFor(originId, title)`,
  `cascadeGoTo(step)`.

- [ ] **Step 1: Add the store slice**

In `ui/src/state/store.ts`, import `CascadeResponse, OriginCandidate` from `../api/types`, then add:

```ts
export interface CascadeSource {
  kind: "query" | "vulnerability";
  title: string;
  branch: string;
}

export interface CascadeState {
  open: boolean;
  question: string;
  loading: boolean;
  error: string | null;
  candidates: OriginCandidate[];
  result: CascadeResponse | null;
  source: CascadeSource | null;
  step: number;
  stepStartedAt: number;
}
```

Add `cascade: CascadeState;` to `OpsState`, and to `initialState`:

```ts
  cascade: {
    open: false,
    question: "What happens if the Strait of Hormuz closes?",
    loading: false,
    error: null,
    candidates: [],
    result: null,
    source: null,
    step: 0,
    stepStartedAt: 0,
  },
```

- [ ] **Step 2: Implement `ui/src/state/cascade.ts`**

```ts
// Impact cascade actions. The map layer and <CascadeStepper /> both read `s.cascade`, so a cascade shown
// from the Impact panel or from a vulnerability branch (Plan B) behaves identically.

import { ApiError, api } from "../api/client";
import type { CascadeResponse, OriginCandidate } from "../api/types";
import { cascadeFocus, clampStep } from "../lib/cascade";
import { message, recordLatency, toast } from "./actions";
import { setOps, useOps, type CascadeSource, type CascadeState } from "./store";

let flyNonce = 0;

function patch(p: Partial<CascadeState>): void {
  setOps((s) => ({ cascade: { ...s.cascade, ...p } }));
}

function flyToStep(result: CascadeResponse, step: number): void {
  const f = cascadeFocus(result, step);
  flyNonce += 1;
  setOps({ flyTo: { lon: f.lon, lat: f.lat, zoom: f.zoom, nonce: flyNonce } });
}

function setStep(step: number): void {
  const { result } = useOps.getState().cascade;
  if (!result) return;
  const next = clampStep(step, result);
  patch({ step: next, stepStartedAt: performance.now() });
  flyToStep(result, next);
}

export function setCascadeOpen(open: boolean): void {
  patch({ open });
}

export function setCascadeQuestion(question: string): void {
  patch({ question });
}

export function showCascade(result: CascadeResponse, source: CascadeSource): void {
  patch({ result, source, step: 0, stepStartedAt: performance.now(), error: null, loading: false, candidates: [] });
  recordLatency(`cascade ${result.origin.name}`, result);
  flyToStep(result, 0);
}

export const cascadeNext = () => setStep(useOps.getState().cascade.step + 1);
export const cascadePrev = () => setStep(useOps.getState().cascade.step - 1);
export const cascadeGoTo = (step: number) => setStep(step);
export const cascadeReset = () => setStep(0);
export function cascadeShowAll(): void {
  const { result } = useOps.getState().cascade;
  if (result) setStep(result.max_degree);
}

export function clearCascade(): void {
  patch({ result: null, source: null, step: 0, candidates: [], error: null });
}

function candidatesOf(err: unknown): OriginCandidate[] {
  if (!(err instanceof ApiError) || err.status !== 422) return [];
  const body = err.body as { candidates?: OriginCandidate[] } | null;
  return Array.isArray(body?.candidates) ? body.candidates : [];
}

export async function askCascade(): Promise<void> {
  const { question } = useOps.getState().cascade;
  patch({ loading: true, error: null, candidates: [] });
  try {
    const result = await api.cascadeAsk({ question, branch: "main" });
    showCascade(result, { kind: "query", title: question, branch: result.branch });
  } catch (err) {
    patch({ loading: false, error: message(err), candidates: candidatesOf(err) });
  }
}

export async function runCascadeFor(originId: string, title: string): Promise<void> {
  patch({ open: true, loading: true, error: null, candidates: [] });
  setOps({ contextMenu: null });
  try {
    const result = await api.cascade({ origin_id: originId, branch: "main" });
    showCascade(result, { kind: "query", title, branch: result.branch });
  } catch (err) {
    patch({ loading: false, error: message(err) });
    toast(`Cascade failed: ${message(err)}`, "error");
  }
}
```

Check that `FlyTarget` in `store.ts` is `{ lon, lat, zoom?, nonce }` (it is) and that `MapView` reacts to
`flyTo` (search `flyTo` in `MapView.tsx`). `actions.ts` must not import `cascade.ts`; that keeps the import
graph acyclic.

- [ ] **Step 3: Implement `ui/src/components/CascadeStepper.tsx`**

```tsx
import { useEffect } from "react";

import { currentStage, degreeCss, headline, ordinal, stepLabel, topHits } from "../lib/cascade";
import { formatLatency } from "../lib/format";
import { flyToNode } from "../state/actions";
import { cascadeGoTo, cascadeNext, cascadePrev, cascadeReset, cascadeShowAll } from "../state/cascade";
import { useOps } from "../state/store";

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** Headline (TuringDB speed + depth), degree ladder, step controls, and the current degree's worst hits. */
export function CascadeStepper() {
  const c = useOps((s) => s.cascade);
  const r = c.result;

  useEffect(() => {
    if (!r) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (typing) return;
      if (e.key === "ArrowRight") cascadeNext();
      if (e.key === "ArrowLeft") cascadePrev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [r]);

  if (!r) return null;
  const h = headline(r);
  const cur = currentStage(r, c.step);
  const maxCount = Math.max(1, ...r.stages.map((s) => s.count));
  const atEnd = c.step >= r.max_degree;

  return (
    <div className="cascade" aria-live="polite">
      <div className="cascade__headline">
        <div className="cascade__big">
          <span className="cascade__num">{h.degrees}</span> degrees
          <span className="cascade__sep">·</span>
          <span className="cascade__num">{h.hops}</span> graph hops
          <span className="cascade__sep">·</span>
          <span className="cascade__num">{h.affected.toLocaleString("en-GB")}</span> facilities
        </div>
        <div className="cascade__speed mono">
          TuringDB: {h.depthLimit}-hop query reached {h.reached.toLocaleString("en-GB")} facilities in{" "}
          <strong>{formatLatency(h.reachMs)} ms</strong> · whole answer {formatLatency(h.totalMs)} ms over {h.queries} queries
        </div>
        <details className="cascade__cypher">
          <summary>Show the deep query</summary>
          <code className="mono">{r.reach.cypher}</code>
        </details>
      </div>

      <p className="cascade__step">{stepLabel(r, c.step)}</p>

      <ol className="cascade__ladder" aria-label="Impact degrees">
        <li className={`cascade__rung cascade__rung--origin${c.step === 0 ? " is-current" : ""}`}>
          <button type="button" onClick={() => cascadeGoTo(0)}>
            <span className="cascade__swatch cascade__swatch--origin" aria-hidden />
            <span className="cascade__deg">Origin</span>
            <span className="cascade__count">{r.origin.name}</span>
          </button>
        </li>
        {r.stages.map((st) => {
          const revealed = st.degree <= c.step;
          return (
            <li key={st.degree} className={`cascade__rung${st.degree === c.step ? " is-current" : ""}${revealed ? "" : " is-hidden"}`}>
              <button type="button" onClick={() => cascadeGoTo(st.degree)} aria-label={`Show up to the ${ordinal(st.degree)} degree`}>
                <span className="cascade__swatch" style={{ background: degreeCss(st.degree) }} aria-hidden />
                <span className="cascade__deg">{ordinal(st.degree)} degree</span>
                <span className="cascade__count">{revealed ? `+${st.count.toLocaleString("en-GB")}` : "?"}</span>
                <span className="cascade__bar" aria-hidden>
                  <span style={{ width: revealed ? `${(100 * st.count) / maxCount}%` : 0, background: degreeCss(st.degree) }} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="cascade__controls">
        <button type="button" className="btn btn--quiet" onClick={cascadePrev} disabled={c.step === 0}>
          ← Back
        </button>
        <button type="button" className="btn btn--primary" onClick={cascadeNext} disabled={atEnd}>
          {c.step === 0 ? "Continue: 1st degree →" : atEnd ? "End of cascade" : `Continue: ${ordinal(c.step + 1)} degree →`}
        </button>
        <button type="button" className="btn btn--quiet" onClick={cascadeShowAll} disabled={atEnd}>
          Show all
        </button>
        <button type="button" className="btn btn--quiet" onClick={cascadeReset} disabled={c.step === 0}>
          Reset
        </button>
      </div>

      {cur ? (
        <ul className="cascade__hits" aria-label={`Most affected at the ${ordinal(cur.degree)} degree`}>
          {topHits(cur, 5).map((hit) => (
            <li key={hit.node.id}>
              <button type="button" onClick={() => flyToNode(hit.node, 6)}>
                <span className="cascade__swatch" style={{ background: degreeCss(cur.degree) }} aria-hidden />
                <span className="cascade__hitname">{hit.node.name}</span>
                <span className="mono cascade__sev">{pct(hit.severity)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {atEnd && r.platforms.length ? (
        <div className="cascade__platforms">
          <h4>Weapon platforms exposed</h4>
          <ul>
            {r.platforms.slice(0, 8).map((p) => (
              <li key={p.name}>
                {p.name} <span className="mono">{pct(p.severity)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : atEnd ? (
        <p className="cascade__note">No weapon platform's final assembly loses at least {pct(r.min_severity)} of its supply.</p>
      ) : null}
    </div>
  );
}
```

`formatLatency(ms)` in `lib/format.ts` accepts `null | undefined` and returns a bare number (no unit), hence the
explicit ` ms`. `flyToNode(node, zoom?)` exists. **`btn--primary` does not exist** in `app.css` (verified):
define it in the cascade CSS section (Step 6). `.chip` exists.

- [ ] **Step 4: Implement `ui/src/components/CascadePanel.tsx`**

```tsx
import { askCascade, clearCascade, runCascadeFor, setCascadeOpen, setCascadeQuestion } from "../state/cascade";
import { useOps } from "../state/store";
import { CascadeStepper } from "./CascadeStepper";
import { ScenarioPrompt } from "./ScenarioPrompt";

const EXAMPLES = [
  "What happens if the Strait of Hormuz closes?",
  "Taiwan Strait blockade",
  "Port of Busan closes",
  "What if the Red Sea closes?",
];

/** "What breaks if X falls?" — one deep TuringDB query, revealed one impact degree at a time. */
export function CascadePanel() {
  const c = useOps((s) => s.cascade);
  if (!c.open) return null;
  const close = () => {
    setCascadeOpen(false);
    if (c.source?.kind === "query") clearCascade();
  };
  return (
    <section className="scenario cascade-panel glass" aria-label="Impact cascade">
      <header className="scenario__head">
        <h3>Impact cascade</h3>
        <button type="button" className="iconbtn" aria-label="Close impact cascade" onClick={close}>
          ×
        </button>
      </header>
      <p className="scenario__hint">
        Name a chokepoint, port or facility. TuringDB walks the supply network in one deep
        query; the map then reveals who loses supply, one degree at a time. Severity = share of a facility's
        inbound supply volume lost; shown when at least 5%.
      </p>
      <ScenarioPrompt
        label="Impact question"
        value={c.question}
        onChange={setCascadeQuestion}
        onSubmit={() => void askCascade()}
        busy={c.loading}
        submitLabel="Ask TuringDB"
        busyLabel="Querying…"
        rows={2}
        placeholder="What happens if the Strait of Hormuz closes?"
      />
      <div className="cascade__examples">
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="chip" onClick={() => setCascadeQuestion(q)}>
            {q}
          </button>
        ))}
      </div>
      {c.error ? <p className="scenario__err mono">{c.error}</p> : null}
      {c.candidates.length ? (
        <div className="cascade__candidates" role="group" aria-label="Choose a place">
          {c.candidates.map((cand) => (
            <button key={cand.node.id} type="button" className="chip" onClick={() => void runCascadeFor(cand.node.id, cand.node.name)}>
              {cand.node.name} <span className="mono">{cand.origin_kind}</span>
            </button>
          ))}
        </div>
      ) : null}
      {c.source?.kind === "query" ? <CascadeStepper /> : null}
    </section>
  );
}
```

The panel shows the stepper only for `source.kind === "query"`; Plan B's panel shows it for vulnerability
cascades, so only one stepper is ever visible.

- [ ] **Step 5: Entry points**

`ui/src/components/BottomBar.tsx`: import `CascadePanel` and `setCascadeOpen`. Add
`const cascadeOpen = useOps((s) => s.cascade.open);`. Inside the `live ? (<> … </>)` fragment, add this as
the **first** button:

```tsx
            <button
              type="button"
              className={`btn btn--quiet bottombar__diff${cascadeOpen ? " is-on" : ""}`}
              aria-pressed={cascadeOpen}
              title="What breaks if a chokepoint, port or facility falls? Step through the impact degree by degree"
              onClick={() => setCascadeOpen(!cascadeOpen)}
            >
              Impact
            </button>
```

Render `<CascadePanel />` after `<ScenarioAgent />`.

`ui/src/components/ContextMenu.tsx`: import `runCascadeFor` from `../state/cascade`. After the "Simulate loss"
button, add:

```tsx
      {["chokepoint", "port", "facility"].includes(node.kind) ? (
        <button type="button" role="menuitem" className="ctxmenu__item" onClick={() => void runCascadeFor(node.id, node.name)}>
          What breaks if this falls?
          <span className="ctxmenu__hint">impact degrees</span>
        </button>
      ) : null}
```

- [ ] **Step 6: CSS (append-only section)**

Append to `ui/src/styles/app.css`:

```css
/* cascade ------------------------------------------------------------------------------------------- */
.cascade-panel { width: 460px; }
.cascade { display: grid; gap: 10px; margin-top: 10px; }
.cascade__headline { padding: 10px 12px; border-radius: 10px; background: rgba(235, 72, 76, 0.08); border: 1px solid rgba(235, 72, 76, 0.35); }
.cascade__big { font-size: 15px; font-weight: 600; }
.cascade__num { font-size: 22px; font-weight: 700; color: #fff; }
.cascade__sep { margin: 0 6px; opacity: 0.5; }
.cascade__speed { margin-top: 4px; font-size: 11.5px; opacity: 0.85; }
.cascade__speed strong { color: #7ee2a8; }
.cascade__cypher { margin-top: 6px; font-size: 11px; }
.cascade__cypher code { display: block; white-space: pre-wrap; word-break: break-word; margin-top: 4px; opacity: 0.8; }
.cascade__step { margin: 0; font-size: 13px; line-height: 1.4; }
.cascade__ladder { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; }
.cascade__rung button { width: 100%; display: grid; grid-template-columns: 14px 92px 64px 1fr; align-items: center; gap: 8px;
  padding: 4px 6px; border-radius: 6px; background: transparent; border: 1px solid transparent; color: inherit; text-align: left; cursor: pointer; }
.cascade__rung.is-current button { border-color: rgba(255, 255, 255, 0.35); background: rgba(255, 255, 255, 0.06); }
.cascade__rung.is-hidden { opacity: 0.4; }
.cascade__swatch { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.cascade__swatch--origin { background: transparent; border: 2px solid rgb(235 72 76); }
.cascade__count { font-variant-numeric: tabular-nums; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cascade__bar { height: 6px; background: rgba(255, 255, 255, 0.07); border-radius: 3px; overflow: hidden; }
.cascade__bar span { display: block; height: 100%; transition: width 400ms var(--ease); }
.cascade__controls { display: flex; gap: 6px; flex-wrap: wrap; }
.cascade__hits, .cascade__platforms ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; font-size: 12px; }
.cascade__hits button { width: 100%; display: grid; grid-template-columns: 14px 1fr auto; gap: 8px; align-items: center;
  background: transparent; border: 0; color: inherit; padding: 3px 4px; cursor: pointer; text-align: left; }
.cascade__hitname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cascade__platforms h4 { margin: 0 0 4px; font-size: 12px; }
.cascade__note { margin: 0; font-size: 12px; opacity: 0.75; }
.cascade__examples, .cascade__candidates { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
```

Also append (verified missing from `app.css`):

```css
.btn--primary { background: rgb(235 72 76); border-color: rgb(235 72 76); color: #fff; font-weight: 600; }
.btn--primary:disabled { opacity: 0.45; cursor: default; }
```

- [ ] **Step 7: Typecheck, test, build**

Run: `npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add ui/src/state/store.ts ui/src/state/cascade.ts ui/src/components/CascadeStepper.tsx ui/src/components/CascadePanel.tsx \
  ui/src/components/BottomBar.tsx ui/src/components/ContextMenu.tsx ui/src/styles/app.css
git commit -m "feat(ui): Impact panel with degree-by-degree cascade stepper

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A7: Map layers — origin, revealed degrees, animated current degree, chokepoint layer

**Files:**
- Create: `ui/src/map/cascadeLayers.ts`
- Modify: `ui/src/map/MapView.tsx`, `ui/src/map/layers.ts`, `ui/src/state/store.ts`, `ui/src/state/actions.ts`,
  `ui/src/components/LayerRail.tsx`
- Test: extend `ui/src/lib/cascade.test.ts`

**Interfaces:**
- Consumes: `curvedPath`, `LonLat` (`lib/arcs.ts`); `degreeColor`, `topHits`, `ordinal`, `currentStage`,
  `visibleStages` (A5); `withAlpha(c: RGBA, alpha: number)`, `RED`, `WHITE` (`map/colors.ts`); `LABEL_FONT`
  from `map/layers.ts`. **It is not exported today** (`const LABEL_FONT = …` at line 23): change it to
  `export const`.
- Produces: `buildCascadeLayers(input: CascadeLayerInput): Layer[]`, `ARC_DRAW_MS`,
  `cascadeAnimating(c, now): boolean`, `stagePaths(stage): LonLat[][]` (cached per stage object).

Visual rules (what the operator sees):
- **Step 0:** origin only. A red pulsing ring, a label `STRAIT OF HORMUZ · CLOSED` (port `· CLOSED`, facility
  `· LOST`), and a `0` badge on it.
- **Step k:** degrees 1..k-1 stay on the map **dimmed** (arcs alpha 0.28, dots alpha 0.55). Degree k **draws
  its arcs** from each parent to its node over `ARC_DRAW_MS = 900 ms` in that degree's colour. Its dots pop in
  as the arcs arrive, sized by severity. Up to 8 of its worst-hit nodes get a badge with the degree number. A
  large label at the stage centroid reads `2ND DEGREE · 18 FACILITIES`.
- Cascade dots are pickable (`{ node }` objects work with `pickedNode`), so hover and click open the existing
  hover card and drawer.

- [ ] **Step 1: Add failing tests for `stagePaths` and `cascadeAnimating`**

Append to `ui/src/lib/cascade.test.ts` (merge the import with the top of the file):

```ts
import { ARC_DRAW_MS, cascadeAnimating, stagePaths } from "../map/cascadeLayers";

describe("cascade layer helpers", () => {
  it("builds one curved path per arc and caches by stage object", () => {
    const st: CascadeStage = {
      ...stage(1, [hit("a", 1, 1)]),
      arcs: [{ source: [0, 0], target: [10, 10], source_id: "0", target_id: "a", hop: 1, rel: "TRANSITED" }],
    };
    const p1 = stagePaths(st);
    expect(p1.length).toBe(1);
    expect(p1[0][0]).toEqual([0, 0]);
    expect(stagePaths(st)).toBe(p1);
  });
  it("animates only for a short while after a step change", () => {
    const c = { result: hormuz, step: 1, stepStartedAt: 1000 };
    expect(cascadeAnimating(c, 1000 + ARC_DRAW_MS / 2)).toBe(true);
    expect(cascadeAnimating(c, 1000 + ARC_DRAW_MS * 3)).toBe(false);
    expect(cascadeAnimating({ ...c, result: null }, 1001)).toBe(false);
  });
});
```

Run: `npm --prefix ui test -- --run src/lib/cascade.test.ts` → FAIL (module missing).

- [ ] **Step 2: Implement `ui/src/map/cascadeLayers.ts`**

```ts
// The impact cascade on the map: origin (degree 0) pulses red; revealed degrees stay dimmed; the newest degree
// draws its arcs from each parent and pops its nodes in, in that degree's colour, with degree-number badges.

import type { Layer } from "@deck.gl/core";
import { TripsLayer } from "@deck.gl/geo-layers";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";

import type { CascadeHit, CascadeResponse, CascadeStage, GraphNode } from "../api/types";
import { curvedPath, type LonLat } from "../lib/arcs";
import { currentStage, degreeColor, ordinal, topHits, visibleStages } from "../lib/cascade";
import { RED, WHITE, withAlpha } from "./colors";
import { LABEL_FONT } from "./layers";

export const ARC_DRAW_MS = 900;
const SETTLE_MS = 400;
const PAST_ARC_ALPHA = 0.28;
const PAST_DOT_ALPHA = 0.55;
const OUTLINE: [number, number, number, number] = [7, 11, 18, 255];

const pathCache = new WeakMap<CascadeStage, LonLat[][]>();

export function stagePaths(stage: CascadeStage): LonLat[][] {
  let paths = pathCache.get(stage);
  if (!paths) {
    paths = stage.arcs.map((a) => curvedPath(a.source, a.target));
    pathCache.set(stage, paths);
  }
  return paths;
}

export function cascadeAnimating(c: { result: CascadeResponse | null; step: number; stepStartedAt: number }, now: number): boolean {
  return Boolean(c.result) && now - c.stepStartedAt < ARC_DRAW_MS + SETTLE_MS;
}

export interface CascadeLayerInput {
  result: CascadeResponse;
  step: number;
  elapsedMs: number; // since the step changed
  now: number; // drives the origin pulse
  reducedMotion: boolean;
}

const posOf = (n: GraphNode): [number, number] => [n.lon as number, n.lat as number];
const located = (n: GraphNode) => n.lon != null && n.lat != null;

function label<T>(id: string, data: T[], extra: Record<string, unknown>): Layer {
  return new TextLayer<T>({
    id,
    data,
    fontFamily: LABEL_FONT,
    fontWeight: 700,
    characterSet: "auto",
    sizeUnits: "pixels",
    outlineWidth: 3,
    outlineColor: OUTLINE,
    fontSettings: { sdf: true },
    ...extra,
  });
}

function originLayers(r: CascadeResponse, now: number, reduced: boolean): Layer[] {
  if (!located(r.origin)) return [];
  const pulse = reduced ? 0.5 : (Math.sin(now / 260) + 1) / 2;
  const suffix = r.origin_kind === "facility" ? "LOST" : "CLOSED";
  return [
    new ScatterplotLayer<GraphNode>({
      id: "cascade-origin-ring",
      data: [r.origin],
      getPosition: posOf,
      getRadius: 12 + 10 * pulse,
      radiusUnits: "pixels",
      stroked: true,
      filled: true,
      getFillColor: withAlpha(RED, 0.25),
      getLineColor: withAlpha(RED, 1 - 0.5 * pulse),
      lineWidthMinPixels: 2.5,
      updateTriggers: { getRadius: now, getLineColor: now },
    }),
    label("cascade-origin-label", [r.origin], {
      getPosition: posOf,
      getText: (n: GraphNode) => `${n.name.toUpperCase()} · ${suffix}`,
      getSize: 13,
      getColor: RED,
      getPixelOffset: [0, -28],
    }),
    label("cascade-origin-badge", [r.origin], { getPosition: posOf, getText: () => "0", getSize: 12, getColor: WHITE }),
  ];
}

function pastLayers(stages: CascadeStage[]): Layer[] {
  return stages.flatMap((st) => [
    new PathLayer<LonLat[]>({
      id: `cascade-past-arcs-${st.degree}`,
      data: stagePaths(st),
      getPath: (p) => p,
      getColor: withAlpha(degreeColor(st.degree), PAST_ARC_ALPHA),
      widthMinPixels: 1,
    }),
    new ScatterplotLayer<CascadeHit>({
      id: `cascade-past-dots-${st.degree}`,
      data: st.hits.filter((h) => located(h.node)),
      getPosition: (h) => posOf(h.node),
      getRadius: (h) => 3 + 5 * h.severity,
      radiusUnits: "pixels",
      getFillColor: withAlpha(degreeColor(st.degree), PAST_DOT_ALPHA),
      pickable: true,
    }),
  ]);
}

function centroid(hits: CascadeHit[]): { lon: number; lat: number } {
  const n = Math.max(1, hits.length);
  return {
    lon: hits.reduce((a, h) => a + (h.node.lon as number), 0) / n,
    lat: hits.reduce((a, h) => a + (h.node.lat as number), 0) / n,
  };
}

function currentLayers(st: CascadeStage, elapsedMs: number, reduced: boolean): Layer[] {
  const color = degreeColor(st.degree);
  const arrived = reduced || elapsedMs >= ARC_DRAW_MS * 0.85;
  const pop = reduced ? 1 : Math.min(1, Math.max(0, (elapsedMs - ARC_DRAW_MS * 0.6) / (ARC_DRAW_MS * 0.5)));
  const hits = st.hits.filter((h) => located(h.node));
  const out: Layer[] = [
    new TripsLayer<LonLat[]>({
      id: `cascade-current-arcs-${st.degree}`,
      data: stagePaths(st),
      getPath: (p) => p,
      getTimestamps: (p) => p.map((_, i) => (ARC_DRAW_MS * i) / Math.max(1, p.length - 1)),
      currentTime: reduced ? Number.MAX_SAFE_INTEGER : elapsedMs,
      trailLength: 1e9,
      fadeTrail: false,
      getColor: withAlpha(color, 0.9),
      widthMinPixels: 2,
      capRounded: true,
      jointRounded: true,
    }),
    new ScatterplotLayer<CascadeHit>({
      id: `cascade-current-dots-${st.degree}`,
      data: hits,
      getPosition: (h) => posOf(h.node),
      getRadius: (h) => (4 + 8 * h.severity) * (0.4 + 0.6 * pop),
      radiusUnits: "pixels",
      stroked: true,
      getFillColor: withAlpha(color, 0.95 * pop),
      getLineColor: withAlpha(WHITE, 0.9 * pop),
      lineWidthMinPixels: 1,
      pickable: true,
      updateTriggers: { getRadius: pop, getFillColor: pop, getLineColor: pop },
    }),
  ];
  if (arrived && hits.length) {
    out.push(
      label(`cascade-badges-${st.degree}`, topHits(st).filter((h) => located(h.node)), {
        getPosition: (h: CascadeHit) => posOf(h.node),
        getText: () => String(st.degree),
        getSize: 12,
        getColor: color,
        getPixelOffset: [0, -14],
      }),
      label(`cascade-stage-title-${st.degree}`, [centroid(hits)], {
        getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
        getText: () => `${ordinal(st.degree).toUpperCase()} DEGREE · ${st.count.toLocaleString("en-GB")} ${st.count === 1 ? "FACILITY" : "FACILITIES"}`,
        getSize: 16,
        getColor: color,
        getPixelOffset: [0, 34],
      }),
    );
  }
  return out;
}

export function buildCascadeLayers(i: CascadeLayerInput): Layer[] {
  const cur = currentStage(i.result, i.step);
  const past = visibleStages(i.result, i.step).filter((s) => s !== cur);
  return [
    ...pastLayers(past),
    ...(cur ? currentLayers(cur, i.elapsedMs, i.reducedMotion) : []),
    ...originLayers(i.result, i.now, i.reducedMotion),
  ];
}
```

If `withAlpha` has a different signature, adapt the calls; do not duplicate it. If `@deck.gl/geo-layers` is
imported elsewhere for `TripsLayer` (check `layers.ts`), use the same import path.

- [ ] **Step 3: Wire into the render loop in `MapView.tsx`**

Import `buildCascadeLayers, cascadeAnimating` from `./cascadeLayers`. In the RAF `loop`, after
`const fxMoving = …`, add:

```ts
      const cas = s.cascade;
      const casActive = Boolean(cas.result);
      const casMoving = casActive && (!reduced || cascadeAnimating(cas, now));
```

Add `casActive ? \`${cas.step}|${casMoving ? now : "still"}\` : ""` to the `key` array. The origin pulse needs
continuous frames while a cascade is shown; with reduced motion, frames are only needed during the step
change. Before `deck.setProps`, add:

```ts
      if (casActive && cas.result) {
        out.push(...buildCascadeLayers({ result: cas.result, step: cas.step, elapsedMs: now - cas.stepStartedAt, now, reducedMotion: reduced }));
      }
```

- [ ] **Step 4: Chokepoint base layer**

- `ui/src/state/store.ts`: add `"chokepoint"` to `LayerKey`, `LAYER_KEYS`, `BaseKind`, `EMPTY_BASE`
  (`chokepoint: []`) and `initialState.layers` (`chokepoint: true`).
- `ui/src/state/actions.ts`: add `"chokepoint"` to `BASE_KINDS` (`grep -n "BASE_KINDS" ui/src/state/actions.ts`).
- `ui/src/components/LayerRail.tsx`: add `{ key: "chokepoint", label: "Chokepoints", glyph: "port" },` after
  ports, and `chokepoint: s.base.chokepoint.length,` to the counts object.
- `ui/src/map/layers.ts`: add `chokepoints: GraphNode[];` to `StaticInput`. In `buildStaticLayers`, when
  `layers.chokepoint`, push the layers below. Read the top of `buildStaticLayers` first and use the helper
  names the file already has (`pos`, `located`, `statusOf`, `statusColor`, `overlay`, `triggers`):

```ts
    const chokes = input.chokepoints.filter(located);
    const CHOKE: RGBA = [120, 200, 255, 255];
    out.push(
      new ScatterplotLayer<GraphNode>({
        id: "chokepoints",
        data: chokes,
        getPosition: pos,
        getRadius: 7,
        radiusUnits: "pixels",
        stroked: true,
        filled: true,
        getFillColor: (n) => withAlpha(statusColor(statusOf(overlay, n.id)) ?? CHOKE, 0.25),
        getLineColor: (n) => statusColor(statusOf(overlay, n.id)) ?? CHOKE,
        lineWidthMinPixels: 1.5,
        pickable: true,
        updateTriggers: { getFillColor: triggers, getLineColor: triggers },
      }),
      new TextLayer<GraphNode>({
        id: "chokepoint-labels",
        data: chokes,
        getPosition: pos,
        getText: (n) => n.name,
        getSize: 11,
        sizeUnits: "pixels",
        getColor: [180, 220, 255, 220],
        getPixelOffset: [0, 14],
        fontFamily: LABEL_FONT,
        fontWeight: 600,
        characterSet: "auto",
        outlineWidth: 3,
        outlineColor: [7, 11, 18, 255],
        fontSettings: { sdf: true },
      }),
    );
```

- `MapView.tsx`: pass `chokepoints: base.chokepoint` into `buildStaticLayers` (the memo already depends on `base`).

- [ ] **Step 5: Run tests, typecheck, build**

Run: `npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ui/src/map/cascadeLayers.ts ui/src/map/MapView.tsx ui/src/map/layers.ts ui/src/state/store.ts \
  ui/src/state/actions.ts ui/src/components/LayerRail.tsx ui/src/lib/cascade.test.ts
git commit -m "feat(ui): degree-by-degree cascade layers and chokepoint layer on the map

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task A8: End-to-end verification in the browser + docs

**Files:**
- Modify: `docs/api.md` (new section "Impact cascade"), `AGENTS.md` (short section at the end)
- Create (if missing): `.claude/launch.json`

- [ ] **Step 1: Start everything**

TuringDB in-memory (A2 Step 1). API with the Bash tool's `run_in_background`:
`OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app --port 8000`. UI via `preview_start`. If
`.claude/launch.json` does not exist, create it:

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "opsmap-ui", "runtimeExecutable": "npm", "runtimeArgs": ["--prefix", "ui", "run", "dev"], "port": 5173 }
  ]
}
```

(`ui/vite.config.ts` proxies `/api/*` to `apiTarget` and strips the `/api` prefix. Read how `apiTarget` is
derived, e.g. from an env var, and start the API on that port, or set the env var to match.)

- [ ] **Step 2: Walk the demo and capture proof**

In the browser pane:
1. Click **Impact**. Keep `What happens if the Strait of Hormuz closes?` and click **Ask TuringDB**.
2. Check: the headline shows 7 degrees · 8 graph hops · ~341 facilities, plus a TuringDB 12-hop time in ms.
   The map flies to Hormuz and shows the pulsing red ring and the `STRAIT OF HORMUZ · CLOSED` label.
   Screenshot.
3. Press **Continue** 7 times (or →). After each press, check: that degree's ladder row is current with a
   `+count`; its arcs draw from the previous degree's nodes in the degree colour; badges show the degree
   number; the stage title appears; earlier degrees are dimmed. Screenshot degrees 1, 2, 3 and 7.
4. Click **Back**, **Show all** and **Reset**; check that the map and ladder follow.
5. Ask `Taiwan Strait blockade`. Check that stepping through the degrees has no multi-second freeze, and note
   the reach-query ms.
6. Ask `Busan Hamburg`. Check that candidate chips appear; click one and the cascade runs.
7. Right-click a facility → **What breaks if this falls?** → the cascade starts from it (degree 1 = its buyers).
8. `read_console_messages` with `onlyErrors: true` → expect none.

- [ ] **Step 3: Docs**

`docs/api.md`: new section **Impact cascade** after the agent routes. Include the endpoints table, the request
and response fields (from the contract), the severity formula, `MIN_SEVERITY`/`MAX_DEGREE`, and the measured
Hormuz/Taiwan timings from Step 2. `AGENTS.md`: new section at the end, **Impact cascade (Plan A)**, at most 10
lines: files, the weighting rule, "read-only, never creates a branch", and "Plan B reuses
`DeepCascade.compute`, `showCascade` and `<CascadeStepper />`".

- [ ] **Step 4: Full regression**

Run: `uv run pytest tests/api tests/agents/test_guard.py tests/agents/test_llm.py -q && npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/api.md AGENTS.md .claude/launch.json
git commit -m "docs: impact cascade API and handoff notes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
