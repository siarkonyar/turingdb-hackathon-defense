# Shared contract: impact cascade (Plan A) + vulnerability branches (Plan B)

Both agents read this file first. It fixes the domain model, the API shapes, the exact Python/TypeScript
interfaces that cross the A/B boundary, file ownership and the git workflow. If an agent needs to change
anything in this file, it stops and asks the user: the other agent builds against it.

- Plan A: `docs/superpowers/plans/2026-10-03-plan-a-impact-cascade.md` ("Hormuz closed: what breaks, degree by degree")
- Plan B: `docs/superpowers/plans/2026-10-03-plan-b-vulnerability-branches.md` ("top-N vulnerabilities, one red branch each")

## Why (challenge 4, TuringDB brief)

Judges look for (1) deep multi-hop queries **at speed**, (2) at least one capability that **depends on
versioning** (branching to simulate an action, replaying, diffing), (3) fused sources / location as queryable
properties. Plan A proves (1) on the map; Plan B proves (2) on the map. Both run on the `supply_chain_deep`
layer inside the fused `theatre` graph.

## Measured facts (live `theatre`, TuringDB 3.0, 3 October 2026)

| Query | Result | Engine time |
|---|---|---|
| `Chokepoint{Hormuz}<-TRANSITED-Consignment-SHIPPED_FROM->Facility` | 163 consignments, 8 facilities | 14 ms |
| same + `-[:SUPPLIES]->{1,12}(g:Facility)` `count(DISTINCT g)` | 2,262 facilities | **8 ms** |
| reach by depth 1/2/3/4/6/8 (Hormuz) | 39 / 294 / 995 / 1,820 / 2,261 / 2,262 | 3-8 ms each (flat) |
| same 12-hop reach from Taiwan Strait (1,162 seed facilities) | 3,925 facilities | ~1,000 ms |
| all `SUPPLIES` edges with `annual_volume` | 21,048 rows | 5 ms |
| `Consignment-LOADED_AT->Port` | 73,809 | 47 ms |

**Unweighted reach is useless for an operator**: Hormuz reaches 2,262 / 4,404 facilities and *all 40* platforms.
So the cascade is **volume-weighted** (below). With `MIN_SEVERITY = 0.05`, a Python prototype gave:

| Origin | Newly affected facilities per degree (1, 2, 3, …) | Total | Platforms ≥ threshold |
|---|---|---|---|
| Strait of Hormuz | 8, 18, 110, 122, 68, 12, 3 | 341 | 0 |
| Taiwan Strait | 1162, 1847, 678, 143, 27 | 3,857 | 19 |
| Bab-el-Mandeb | 1410, 1500, 391, 37, 2 | 3,340 | 8 |
| Strait of Malacca | 1357, 1560, 487, 68, 12, 1 | 3,485 | 9 |

Hormuz is the demo: small start, visible growth, tapering tail over 7 degrees.

## Domain model (both plans use exactly this)

**Origin kinds:** `chokepoint` (label `Chokepoint`), `port` (label `Port`), `facility` (label `Facility`).

**Degree** = impact step shown to the operator. **Graph hops** = edges actually traversed.

- Degree 0 = the origin (status `lost`).
- Seeds (the first affected facilities) and their severity:
  - chokepoint: every Facility with a Consignment `SHIPPED_FROM` it that `TRANSITED` the chokepoint.
    `severity = transiting consignments / all consignments shipped from that facility`. Seed degree **1**.
  - port: same with `LOADED_AT` instead of `TRANSITED`. Seed degree **1**.
  - facility: the origin facility itself, severity `1.0`, seed degree **0** (its buyers are degree 1).
- Propagation along `(a:Facility)-[:SUPPLIES {annual_volume}]->(b:Facility)` (a supplies b), breadth-first,
  each facility assigned once at its first degree:
  `severity(b) = min(1, Σ over frontier suppliers a→b of severity(a) * volume(a,b) / inbound_volume(b))`
  where `inbound_volume(b)` = sum of `annual_volume` over **all** SUPPLIES edges into b on that ref.
  Keep b only if `severity(b) >= min_severity` (default `MIN_SEVERITY = 0.05`); only kept nodes propagate.
  `parent(b)` = the frontier supplier with the largest `severity(a) * volume(a,b)` (ties: smaller facility_id).
  Stop at `MAX_DEGREE = 12` or when a degree adds nobody.
- Graph hops: chokepoint/port origin = `max_degree + 1` (2 edges to reach seeds, 1 per later degree);
  facility origin = `max_degree`.
- Platform exposure: `(p:Platform)-[:PRODUCED_AT]->(f:Facility)`; exposure(p) = max severity over affected
  facilities f of p. Listed only for affected f.
- Impact score (Plan B ranking) = Σ severity over affected facilities with degree ≥ 1, rounded to 2 dp
  ("facility-equivalents of output disrupted"). Tie-break: more affected facilities, then name.

These are explainable, game-free proxies, not calibrated forecasts; the UI says "severity = share of
inbound supply volume lost".

## API shapes (pydantic in `api/models.py`, mirrored in `ui/src/api/types.ts`) — owned by Plan A

```python
OriginKind = Literal["chokepoint", "port", "facility"]

class CascadeHit(Frozen):
    node: Node                 # located Facility node (status "at_risk")
    degree: int                # >= 1
    severity: float            # 0..1, rounded to 3 dp
    parent_id: str | None      # Node.id of the parent (origin Node.id for seeds of a chokepoint/port)
    via: str                   # "TRANSITED" | "LOADED_AT" | "SUPPLIES"

class CascadeStage(Frozen):
    degree: int
    hits: list[CascadeHit]     # sorted by severity desc
    arcs: list[Arc]            # parent -> hit, Arc.hop == degree, Arc.rel == via
    count: int
    mean_severity: float

class ReachProbe(Frozen):
    cypher: str                # the single deep variable-length query that was timed
    depth_limit: int           # MAX_DEGREE
    reached: int               # count(DISTINCT g) unweighted
    ms: float | None           # TuringDB engine time for that one query

class PlatformExposure(Frozen):
    name: str
    archetype: str | None
    severity: float
    facility_id: str           # Node.id of the affected final-assembly facility

class CascadeRequest(Frozen):
    origin_id: str = Field(min_length=1, max_length=64)       # Node.id (TuringDB int id as str)
    branch: str = Field(default="main", min_length=1, max_length=64)
    min_severity: float = Field(default=0.05, ge=0.01, le=0.5)

class CascadeAskRequest(Frozen):
    question: str = Field(min_length=2, max_length=400)
    branch: str = Field(default="main", min_length=1, max_length=64)
    min_severity: float = Field(default=0.05, ge=0.01, le=0.5)

class OriginCandidate(Frozen):
    node: Node
    origin_kind: OriginKind
    score: float               # resolution confidence 0..1

class OriginsResponse(Frozen):
    query: str
    candidates: list[OriginCandidate]

class CascadeResponse(Timed):
    branch: str
    origin: Node               # status "lost"
    origin_kind: OriginKind
    min_severity: float
    stages: list[CascadeStage] # stages[i].degree == i + 1, no gaps
    max_degree: int            # == len(stages)
    graph_hops: int
    total_affected: int
    reach: ReachProbe
    platforms: list[PlatformExposure]  # sorted by severity desc
```

`Node.kind` gains `"chokepoint"` (Plan A). `Branch.kind` (`BranchKind`) gains `"vulnerability"` (Plan B).

Vulnerability branches carry a `(:VulnerabilityBranch {rank, label, spec})` marker (Plan B), **not**
`AgentBranch`: the agents' `BranchLab` ledger parses every `AgentBranch` spec as JSON and replays it after a
restart, and must never see these. `spec` is base64url(JSON).

## Endpoints

| Owner | Method + path | Body / query | Returns |
|---|---|---|---|
| A | `GET /cascade/origins?q=hurmuz` | | `OriginsResponse` (max 8) |
| A | `POST /cascade` | `CascadeRequest` | `CascadeResponse` (read-only, no branch created) |
| A | `POST /cascade/ask` | `CascadeAskRequest` | `CascadeResponse`; 422 `{detail, candidates}` if ambiguous/no match |
| B | `POST /vulnerabilities/scan` | `{top: 1..5 = 3, kinds: OriginKind[] = all, min_severity = 0.05}` | `VulnerabilitiesResponse` |
| B | `GET /vulnerabilities` | | `VulnerabilitiesResponse` (rebuilt from branch markers) |
| B | `GET /vulnerabilities/{branch}/cascade` | | `CascadeResponse` computed **on that branch** |
| B | `DELETE /vulnerabilities` | | 204, discards every vulnerability branch |

All are mounted only when `OPSMAP_BACKEND=turingdb` (like `/agent/*`); mounting failure is logged, never fatal.

## Cross-boundary Python interface (Plan A produces, Plan B consumes)

`api/deep_cascade.py` (pure, no I/O):

```python
MIN_SEVERITY = 0.05
MAX_DEGREE = 12

@dataclass(frozen=True)
class SupplyNetwork:
    out_edges: Mapping[str, tuple[tuple[str, float], ...]]  # facility_id -> ((buyer facility_id, volume), ...)
    inbound: Mapping[str, float]                              # facility_id -> total inbound volume

@dataclass(frozen=True)
class Seeds:
    severities: Mapping[str, float]  # facility_id -> severity in (0, 1]
    degree: int                      # 1 for chokepoint/port, 0 for facility
    via: str                         # "TRANSITED" | "LOADED_AT" | "SUPPLIES"

@dataclass(frozen=True)
class Hit:
    facility_id: str
    degree: int
    severity: float
    parent: str | None  # parent facility_id; None for seeds (their parent is the origin)
    via: str

def propagate(seeds: Seeds, network: SupplyNetwork, min_severity: float = MIN_SEVERITY,
              max_degree: int = MAX_DEGREE) -> list[list[Hit]]: ...
    # index 0 = degree 1. For a facility origin, the origin itself is NOT returned.

def impact_score(layers: Sequence[Sequence[Hit]]) -> float: ...  # Σ severity, 2 dp
```

`api/deep_cascade_live.py`:

```python
@dataclass(frozen=True)
class FacilityIndex:
    by_fid: Mapping[str, Node]   # facility_id -> Node
    fid_by_id: Mapping[str, str] # Node.id -> facility_id
    platforms: Mapping[str, tuple[tuple[str, str | None], ...]]  # facility_id -> ((platform name, archetype), ...)

@dataclass(frozen=True)
class Origin:
    node: Node          # status "lost"
    kind: OriginKind
    key: str            # waypoint_id / port_id / facility_id (patterns match on it: fast index lookup)

class DeepCascade:
    def __init__(self, backend: TuringBackend) -> None: ...
    def session(self, ref: Ref, sw: Stopwatch | None = None) -> Session: ...  # backend.session wrapper
    def network(self, s: Session) -> SupplyNetwork: ...                      # cached per (branch, head)
    def facility_index(self, s: Session) -> FacilityIndex: ...               # cached per (branch, head)
    def origin(self, s: Session, origin_id: str) -> Origin: ...              # NotFound / ValueError
    def seeds(self, s: Session, origin: Origin) -> Seeds: ...
    def seeds_by_origin(self, s: Session, kind: Literal["chokepoint", "port"]) -> dict[str, Seeds]: ...
        # one aggregated query; key = origin Node.id
    def catalog(self, s: Session) -> list[tuple[Node, OriginKind]]: ...      # all chokepoints, ports, facilities
    def compute(self, ref: Ref, origin_id: str, min_severity: float = MIN_SEVERITY) -> CascadeResponse: ...
```

`TuringBackend.session(ref: Ref, sw: Stopwatch) -> Session` (public wrapper of `_session`) is added by Plan A.

## Cross-boundary UI interface (Plan A produces, Plan B consumes)

`ui/src/state/cascade.ts`:

```ts
export interface CascadeSource { kind: "query" | "vulnerability"; title: string; branch: string }
export function showCascade(result: CascadeResponse, source: CascadeSource): void; // step := 0
export function cascadeNext(): void;
export function cascadePrev(): void;
export function cascadeShowAll(): void;
export function cascadeReset(): void;   // step := 0
export function clearCascade(): void;   // removes cascade layers + result
```

Store slice `cascade: CascadeState` in `ui/src/state/store.ts`:

```ts
export interface CascadeState {
  open: boolean;           // Plan A's Impact panel is open
  question: string;
  loading: boolean;
  error: string | null;
  candidates: OriginCandidate[];
  result: CascadeResponse | null;
  source: CascadeSource | null;
  step: number;            // 0 = only origin + headline; k = degrees 1..k revealed
  stepStartedAt: number;   // performance.now() when step last changed (arc draw animation)
}
```

`ui/src/components/CascadeStepper.tsx`: `export function CascadeStepper()` — reads the slice itself;
renders headline, degree ladder, Continue/Back/Show all/Reset and the current-degree top list. Plan B embeds
`<CascadeStepper />` inside its own panel. The map cascade layer reads the same slice, so it works no matter
which panel triggered it.

`ui/src/lib/cascade.ts`: `DEGREE_COLORS`, `degreeColor(d)`, `degreeCss(d)`, `ordinal(d)` (Plan B uses them
for consistent colours in the branch tree).

## File ownership (avoid edit collisions)

| Area | Plan A owns | Plan B owns | Shared (small, additive edits only) |
|---|---|---|---|
| Backend | `api/deep_cascade.py`, `api/deep_cascade_live.py`, `api/cascade_resolve.py`, `api/cascade_routes.py` | `api/vulnerability.py` (pure), `api/vulnerability_lab.py` (live), `api/vulnerability_routes.py` | `api/models.py` (A: cascade models + chokepoint kind; B: vulnerability models + BranchKind), `api/main.py` (one mount line each), `api/backends/turing.py` (A: `session()`, chokepoint KIND_QUERIES/SNAPSHOT_KINDS/meta; B: `_describe_change` role + `DISCARDABLE`), `api/nodes.py` (A) |
| UI | `lib/cascade.ts`, `state/cascade.ts`, `components/CascadeStepper.tsx`, `components/CascadePanel.tsx`, `map/cascadeLayers.ts` | `lib/vulnerability.ts`, `state/vulnerabilities.ts`, `components/VulnerabilityPanel.tsx`, `components/VulnerabilityTree.tsx`, `map/vulnLayers.ts` | `api/types.ts`, `api/client.ts`, `state/store.ts`, `map/MapView.tsx`, `components/BottomBar.tsx`, `components/BranchSwitcher.tsx` (B), `components/ContextMenu.tsx` (A), `styles/app.css` (append-only sections headed `/* cascade */` and `/* vulnerabilities */`), `map/colors.ts` (A) |
| Tests | `tests/api/test_deep_cascade.py`, `test_cascade_resolve.py`, `test_cascade_routes.py`, `test_deep_cascade_live.py`, `ui/src/lib/cascade.test.ts` | `tests/api/test_vulnerability.py`, `test_vulnerability_routes.py`, `test_vulnerability_live.py`, `ui/src/lib/vulnerability.test.ts` | — |
| Docs | `docs/api.md` section "Impact cascade" | `docs/api.md` section "Vulnerability branches" | `AGENTS.md` (one short section each, at the end) |

## Git workflow

0. **Precondition (user):** the working tree has large uncommitted wargame/JEV work. Commit it first on
   `claude/supply-chain-threat-defence-3gi0qk` (or stash it), otherwise the worktrees will not contain it.
1. Agent A: worktree + branch `feat/impact-cascade` from that commit.
2. Agent B: worktree + branch `feat/vulnerability-branches` from the same commit. B does its pure/offline
   tasks first (B1, B4). Before B's live/integration tasks, B runs `git merge feat/impact-cascade`
   (A commits task by task; B merges once A3 is committed for backend work, A6 for UI work).
3. Commits: conventional (`feat:`, `test:`, `docs:`), one per task, ending with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
4. Never commit `graphs/theatre/`, `matches/*.json`, `.env`.

## Runtime rules that bite (from AGENTS.md)

- The server must run in-memory before creating branches: `uv run turingdb stop -turing-dir "$(pwd)"` then
  `uv run turingdb start -turing-dir "$(pwd)" -demon -in-memory -load theatre -start-timeout 20000`.
- No change-on-change: every branch is cut from main. A client checked out on a change cannot `new_change()`.
- Never `CHANGE SUBMIT`; never write main.
- Unknown label/property names are errors; use `Session.labels` / `has_props`.
- Strings in Cypher go through `string_literal`; JSON stored in a property must be base64 (quotes get mangled).
- Expressions nest ≤ 256 levels: use `id_clauses` (chunks of 200) for id lists.
- Do not `pkill -f "turingdb start"`. Do not run two live suites at once against the same server.
