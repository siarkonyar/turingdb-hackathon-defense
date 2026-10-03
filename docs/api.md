# OpsMap API

The HTTP contract behind the OpsMap operating picture (`ui/`). Agents and scripts can call the same
endpoints. The authoritative shapes are the pydantic models in [`api/models.py`](../api/models.py), and
FastAPI serves them as OpenAPI at `/docs` and `/openapi.json`.

```bash
uv run uvicorn api.main:app --port 8000                          # mock fixtures (default)
OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app --port 8000  # live `theatre` graph
```

| Env var | Default | Meaning |
|---|---|---|
| `OPSMAP_BACKEND` | `mock` | `mock` serves `api/mock/fixtures/`; `turingdb` queries a TuringDB server. The one switch between the two. |
| `TURINGDB_HOST` | `http://localhost:6666` | TuringDB server URL (live backend) |
| `TURINGDB_GRAPH` | `theatre` | Graph to serve (live backend) |
| `OPSMAP_CORS` | Vite dev/preview origins | Comma-separated allowed origins |
| `OPSMAP_FIXTURES` | `api/mock/fixtures` | Fixture directory (mock backend) |
| `OPSMAP_MATCHES_DIR` | `matches/` | Where wargame matches are saved and replayed from (live backend) |
| `FEATHERLESS_API_KEY` | unset | LLM key for the agents. Without it, everything except replay reports `LLM unavailable` |

Every variable can also be set in a gitignored `.env` at the repo root (copy `.env.example`); real environment
variables win. With `OPSMAP_BACKEND=turingdb` and `FEATHERLESS_API_KEY` in `.env`, a plain
`uv run uvicorn api.main:app` serves the live graph with the agents and the wargame.

Both backends return identical shapes, so a client cannot tell them apart except through `engine`.

## Conventions

- **Refs.** Every `branch`, `a`, `b` and `base_branch` parameter is a ref: `main`, a TuringDB change id
  (`4`), or either one pinned to a commit (`main@313a10dec2245f64`, `4@ddbd8da1`). Branches are TuringDB
  changes. Strikes and hypotheses are never submitted, so `main` is never modified.
- **Node ids** are TuringDB internal node ids as strings (live) or fixture ids (mock). Treat them as opaque.
- **Timing.** Every response except `/health` and `/meta` carries:
  - `engine`: `turingdb` or `fixtures`.
  - `latency_ms`: summed **server-side** TuringDB execution time (`get_query_exec_time()`). This is what
    the UI's latency KPI shows.
  - `roundtrip_ms`: wall-clock time spent in the backend (SDK, HTTP, pandas).
  - `queries`: `[{cypher, ms}]`, every Cypher statement that ran.
- **Statuses** on a node: `at_risk` (amber), `no_power` (amber, a site or supplier whose every power feed
  is gone) and `lost` (red, deleted on that branch). A missing `status` means nominal.
- **Null fields are omitted** from `/nodes` and `/diff` (large payloads), so treat every optional `Node`
  field as possibly absent.
- **Errors** are `{"detail": "..."}` with `404` (unknown node or branch), `409` (illegal write, e.g.
  striking a hypothesis branch), `422` (bad input) or `502`/`503` (TuringDB query failed / unreachable).

### Node

```json
{"id": "168", "kind": "plant", "label": "PowerPlant", "name": "TBEA Awati", "lat": 40.5, "lon": 80.174,
 "source": "power_plants", "timestamp": null, "synthetic": null, "status": null, "importance": 0.37,
 "fuel": "Solar", "capacity_mw": 20.0, "exposure": null, "confidence": null}
```

`kind` is one of `plant | site | supplier | drone | crime | report | part | facility | port | other` (`facility` and `port` come from the supply_chain_deep layer). `importance` (0..1)
drives glyph size: plants scale by `capacity_mw` (log). `exposure` (sites and suppliers) counts the attack
scenarios that target the systems the asset `RUNS`.

## Endpoints

### `GET /nodes?bbox&types&branch`

Located nodes for the map.

| Param | Example | Notes |
|---|---|---|
| `bbox` | `-10,35,30,60` | `west,south,east,north` (MapLibre `getBounds()` order). Crossing the antimeridian is allowed. Omit for the whole world. |
| `types` | `plant,site` | Comma list of kinds (`plant, site, supplier, drone, crime, report, part, facility, port`). Omit for all. |
| `branch` | `main` | Ref. Nodes carry their `status` on that branch. |

Returns `{branch, nodes: Node[], ...timing}`. All 34,942 plants plus sites come back in about 250 ms of
TuringDB time on the first call, and per-(branch, commit, kind) results are cached after that.

### `GET /node/{id}/neighbours?branch`

Returns `{branch, node, properties, groups}`. `properties` holds every property of the node. `groups` is
`[{rel, direction: "out" | "in", total, nodes}]`, one entry per edge type and direction, sorted by importance
and capped at 40 nodes (`total` is the true count). Example for SITE01: `POWERED_BY` out 3, `PATROLS` in 20,
`NEAR` in 1653, `DELIVERED_TO` in 4093.

### `POST /simulate`

```json
{"node_id": "47937", "base_branch": "main"}
```

Strike simulation. On `main`, the API opens a new TuringDB change. On a strike branch, the strike stacks
onto that branch. Hypothesis branches return `409`. The API then:

1. Walks the dependency cascade backwards from the struck node (`api/cascade.py`). It follows
   `POWERED_BY` from plants, `SUPPLIED_BY`/`SOURCES_FROM` from suppliers, `FOR_PART`→`DELIVERED_TO` from
   parts and `PATROLS` from sites, up to 6 hops, using one batched query per rule per hop.
2. Writes a `(:Strike {struck_id, name, created})` marker, `DELETE`s the node and `COMMIT`s.
3. Marks each affected site or supplier `no_power` if no `POWERED_BY` feed survives, `at_risk` otherwise.
   It stores these as `ops_status` on the branch and commits.

Response:

```json
{
  "branch": "5", "base_branch": "main",
  "struck":   Node,                                  // status "lost"
  "affected": [{"node": Node, "hop": 1, "via": "POWERED_BY", "parent_id": "24786"}],
  "lost":     [Node],                                // struck + every no_power node
  "arcs":     [{"source": [lon, lat], "target": [lon, lat], "source_id": "...", "target_id": "...",
                "hop": 1, "rel": "POWERED_BY"}],     // non-located hops (parts) collapsed
  "kpis":     {"assets_at_risk": 26, "sites_without_power": 0, "suppliers_without_power": 0, "parts_affected": 11},
  "latency_ms": 10.3, "roundtrip_ms": 53.5, "engine": "turingdb", "queries": [...]
}
```

`kpis` cover the whole branch, so stacked strikes accumulate. Measured on `theatre` (live): supplier SUP040
reaches 37 affected nodes in 10 ms of TuringDB time and 54 ms round trip.

### `DELETE /branches/{id}`

Discards a strike branch (`CHANGE DELETE`), then returns `204`. Any other kind of branch returns `409`.

### `GET /diff?a&b`

Compares two refs (branches or commits) over the located kinds plus parts. Returns
`{a, b, added: Node[], removed: Node[], changed: [{node, fields: {field: [value_on_a, value_on_b]}}]}`.
TuringDB has no diff command, so the API diffs two snapshots read at each ref.

### `GET /branches`

```json
{"branches": [
  {"id": "main", "kind": "main", "label": "main",
   "commits": [{"hash": "c785273b8fbf8d61", "index": 1, "node_delta": 294179, "edge_delta": 845504, "time": null}, ...]},
  {"id": "3", "kind": "hypothesis", "label": "H2 · Wedel degraded, operational", "confidence": 0.65,
   "description": "..."},
  {"id": "5", "kind": "strike", "label": "Strike · Supplier: SUP040"}
]}
```

`commits` (main only) drive the time slider. `time` is the latest `Report` timestamp visible at that
commit. A change counts as a **hypothesis** if it contains a `(:Hypothesis {name, confidence,
description})` node, as a **strike** if it contains `(:Strike)`, and as a plain `change` otherwise.

To create hypothesis branches on the live graph (idempotent; `--reset` recreates them), run:

```bash
OPSMAP_BACKEND=turingdb uv run python -m api.seed_hypotheses
```

This seeds three competing branches grounded in the `CONTRADICTS` report pairs (Wedel destroyed vs
degraded, EC Rzeszów sabotaged). Changes are not persisted by an `-in-memory` server, so rerun the
command after every server start.

### `GET /reports?until&branch`

`Report` nodes up to an ISO-8601 instant (`until=2026-09-30T12:00:00Z`), oldest first:
`{report_id, text, claim, source_type, mentions: [node ids], contradicts: node id | null, node: Node}`.
`node.confidence` is the report's confidence.

### `GET /tracks?branch`

Drone tracks for the deck.gl `TripsLayer`: `[{id, name, path: [[lon, lat]...], timestamps: [epoch s...]}]`.
The API keeps every 6th reading.

### `GET /meta`, `GET /health`

`/meta` returns `{engine, graph, layers}`. `/health` returns `{"status": "ok"}`.

## Agents and the wargame (live backend only)

Mounted when `OPSMAP_BACKEND=turingdb`. Every agent action is a **background job**: the `POST` returns at
once (`202`) with an id, the work runs on a worker thread (LLM calls and TuringDB branch builds never block
the HTTP server), and progress arrives as **server-sent events**. Agent branches show up in `/branches`
and `/diff` like any other change, so the map can follow them.

### SSE streams

`GET /agent/jobs/{job_id}/events` and `GET /match/{match_id}/events` return `text/event-stream`. Each event
has an `id` (0, 1, 2, ...), an `event:` name and a JSON `data:` object that repeats the name as `type`. A
client that reconnects with `Last-Event-ID: n` resumes at event `n+1`, so it never receives duplicates. A
late subscriber first gets every past event, then follows live. Every stream starts with `job_started`,
ends with `done {status: done|stopped|error}` and then closes. An idle stream sends a `: heartbeat`
comment every 15 s.

```
id: 3
event: move
data: {"type": "move", "round": 1, "side": "red", "label": "Strike supplier SUP012", ...}
```

### One-shot agents

| Endpoint | Body | Job events |
|---|---|---|
| `GET /agent/status` | | `{available, model?, reason?, graph}` (not a job) |
| `POST /agent/scenario` | `{question, max_steps=16}` | `step*`, `result {branch, explanation, headline, impact_diff, steps, model}` |
| `POST /agent/threat` | `{threat_steps=16}` | `step*`, `result {result, steps, model, branches}` |
| `POST /agent/defence` | `{threat_branch, max_steps=16}` | `step*`, `result {result, steps, model}` |
| `POST /agent/redblue` | `{threat_steps=16, defence_steps=16}` | `step*` (both agents), `result {headline, threat_branch, defence_branch, ...}` |
| `GET /agent/jobs/{id}` | | `{id, kind, status, events, result}` |

Each returns `{job_id}`. A `step` is `{agent, action, thought, args, observation}`, one per tool call, as it
happens. A failure is an `error {message}` event, followed by `done {status: "error"}`.

### Matches (turn-based red vs blue)

A match starts on a **base branch** (`main` or a scenario branch). Each round, red plays ONE disruption as a
branch stacked on the current head, then blue plays ONE countermeasure stacked on red's branch. The head
moves forward each time. TuringDB 3.0 cannot open a change on top of a change, so a stacked branch is cut
from `main` and replays its parent's recorded edits first (the lineage). Loss is measured **against the
base**, so after a scenario the numbers mean "additional damage on top of the scenario".

| Endpoint | Body | Returns |
|---|---|---|
| `POST /match` | `{base_branch="main", rounds=6, strategic=true, seed=7}` (1-6 rounds) | `202 {match_id}`; the match runs in the background |
| `GET /match/{id}/events` | | SSE, see below |
| `GET /match/{id}` | | `{id, kind, status, head, moves: Move[]}` |
| `POST /match/{id}/inject` | `{text}` | `202 {queued}`; the event is applied before the next round |
| `POST /match/{id}/pause` · `/resume` · `/stop` | | `200`; takes effect between moves (`409` once finished) |
| `POST /match/replay` | `{file, speed=1.0}` | `202 {match_id}`; stream it with `/match/{id}/events` |
| `GET /matches/{file}/download?format=md` | `format=md` (default) or `json` | Attachment: readable move script or full replay recording; no LLM calls |
| `GET /matches` | | `{matches: [{file, id, created, base_branch, rounds, status, moves, final_loss_pct, model}]}` |

Match events, in order:

| Event | Data |
|---|---|
| `match_started` | `{match_id, base_branch, rounds, base_loss_pct, model}` |
| `move_started` | `{round, side: red\|blue\|inject, head}` before every move |
| `move` | a `Move` (below) |
| `inject` | `{text, branch, move: Move}`: an operator event became the head (`side: "inject"`) |
| `round_done` | `{round, head, loss_pct, abs_loss_pct}` |
| `status` | `{state: paused\|running}` |
| `match_done` | `{status: done\|stopped\|error, summary}` |
| `error` | `{message, replay_available}` (e.g. the LLM is unavailable) |

```json
{"round": 1, "side": "red", "action": "strike_supplier", "args": {"supplier_id": "SUP012"},
 "actions": [{"action": "strike_supplier", "args": {"supplier_id": "SUP012"}}],
 "branch_id": "37", "parent_id": "36", "label": "Strike supplier SUP012",
 "rationale": "SUP012 carries the most class-A demand", "loss_pct": 3.7, "abs_loss_pct": 17.5,
 "llm_ms": 2140.2, "db_ms": 1785.0, "latency_ms": 3925.2, "fallback": false,
 "targets": [{"id": "47937", "name": "Supplier: SUP012", "kind": "supplier", "lat": 51.2, "lon": 6.8}],
 "arcs": [{"source": [6.8, 51.2], "target": [7.1, 50.9], "source_id": "47937", "target_id": "51002",
           "hop": 1, "rel": "DEPENDS_ON"}]}
```

- `loss_pct` is additional projected loss vs the base (percentage points); `abs_loss_pct` is the absolute
  loss of the branch.
- `llm_ms` is model time and `db_ms` is the rest of the move (TuringDB branch build, evaluation, diff).
- `targets`/`arcs` drive the map: for red, the destroyed nodes and arcs to the newly affected ones; for
  blue, the protected/re-powered asset and the nodes it restored.
- `fallback: true` means the model gave no valid move within its budget (one decision, at most 3 model
  calls) and the top-ranked default was played.

Every match is saved to `matches/<id>.json` as it runs: `{id, created, base_branch, base_actions,
base_loss_pct, rounds, status, model, moves, events: [{type, t, at, data}], summary}`, where `t` is seconds
since the start. **Replay** plays it back with that timing and **no LLM calls**: it rebuilds every branch from
the recorded edits (so TuringDB must be up), emits the same events with the new branch ids and
`replay: true`. Use it as the demo fallback when the LLM is down (`speed` > 1 plays faster).

The CLI wraps the same functions:

```bash
uv run python -m agents.match --base 25 --rounds 3 --inject 2:"the Liverpool port is closed" --save-as demo
uv run python -m agents.match --replay demo
```

## Impact cascade (live backend only)

"What breaks if X falls?" over the `supply_chain_deep` layer of `theatre`. Read-only: it never creates a branch
and works on `main` or any existing branch ref. Mounted only when `OPSMAP_BACKEND=turingdb`.

| Method + path | Body / query | Returns |
|---|---|---|
| `GET /cascade/origins?q=hormuz&branch=main` | `q` 2..120 chars | `OriginsResponse {query, candidates: OriginCandidate[]}` (max 8) |
| `POST /cascade` | `CascadeRequest {origin_id, branch="main", min_severity=0.05 (0.01..0.5)}` | `CascadeResponse`; 404 unknown node, 422 not a chokepoint/port/facility |
| `POST /cascade/ask` | `CascadeAskRequest {question (2..400), branch, min_severity}` | `CascadeResponse`, or **422** `{detail, candidates}` when no place or several places match |

`question` is free text ("What happens if the Strait of Hormuz closes?", "What if Europe's biggest port shuts?").
Resolution runs in two steps:

1. **Deterministic** (`api/cascade_resolve.py`): chokepoint aliases plus name-token matching over every
   chokepoint, port, facility, company, country, power plant and supply item (~48k names, 30-250 ms). A
   confident, unambiguous match runs immediately, with no model involved.
2. **LLM fallback** (`agents/place_extractor.py`, Featherless, one bounded call, 60 s timeout): only when step 1
   is not confident. The model only turns the question into concrete entity names ("Europe's biggest port" ->
   "Port of Rotterdam"); those names go back through step 1. It never queries the graph or estimates impact.
   The name it used is returned as `understood_as`. Without `FEATHERLESS_API_KEY`, or when the call fails, the
   endpoint answers from step 1 alone.

Several confident matches (e.g. "Busan Hamburg") return 422 with them as `candidates` (chips in the UI, which
then call `POST /cascade`). If nothing matches, the 422 says it is not connected to anything in the TuringDB graph
dataset. An entity that exists but has no link into the supply network (e.g. a solar park powering no facility)
returns 200 with `connected: false` and no stages.

**Origin kinds.** `chokepoint`, `port`, `facility` as below, plus entities that reach facilities through one
edge: `company` (facilities `OPERATED_BY` it), `country` (facilities `LOCATED_IN` it), `plant` (facilities
`POWERED_BY` it; seed severity = 1 / that facility's number of power feeds) and `item` (minerals, materials,
components, assemblies, subsystems, systems: facilities it is `PRODUCED_AT`). Their seeds are degree 1 with
severity 1 (plants: as above). Companies and items have no coordinates and are drawn at their facilities' centroid.

**Model.** Degree 0 is the origin (`status: "lost"`). Seeds (degree 1) for a chokepoint/port are the
facilities that ship consignments through it (`TRANSITED` / `LOADED_AT`), with
`severity = transiting consignments / all consignments shipped from that facility`. A facility origin's buyers
are degree 1. Propagation follows `(a:Facility)-[:SUPPLIES {annual_volume}]->(b:Facility)` breadth-first:

    severity(b) = min(1, Σ over affected suppliers a of severity(a) * volume(a,b) / inbound_volume(b))

kept when `>= min_severity` (`MIN_SEVERITY = 0.05`), at most `MAX_DEGREE = 12` degrees. Each facility is
reported once, at its first degree; `parent_id` is its biggest contributor. Severity is the share of a
facility's inbound supply volume lost: an explainable proxy, not a calibrated forecast.

`CascadeResponse` (plus `Timed` fields `latency_ms`, `roundtrip_ms`, `queries`):

| Field | Meaning |
|---|---|
| `origin`, `origin_kind` | origin node (`lost`), `chokepoint` / `port` / `facility` / `company` / `country` / `plant` / `item` |
| `stages[]` | `{degree, hits[], arcs[], count, mean_severity}`; `stages[i].degree == i + 1`; hits sorted by severity |
| `hits[]` | `{node (at_risk), degree, severity, parent_id, via: TRANSITED / LOADED_AT / SUPPLIES}` |
| `arcs[]` | parent → hit, `hop == degree`, `rel == via` |
| `max_degree`, `graph_hops` | degrees reached; edges walked (`max_degree + 1` for a chokepoint/port) |
| `total_affected` | sum of stage counts |
| `reach` | `{cypher, depth_limit: 12, reached, ms}`: the one deep `-[:SUPPLIES]->{1,12}` query, unweighted, timed by TuringDB |
| `connected` | `false` when the origin has no link into the supply network |
| `understood_as` | entity name the LLM extracted, when step 2 was needed |
| `platforms[]` | `{name, archetype, severity, facility_id}`: weapon platforms whose final-assembly facility is affected |

Measured on the live in-memory `theatre` (TuringDB 3.0, laptop, 3 October 2026):

| Origin | Degrees (new facilities per degree) | Total | Graph hops | 12-hop reach query |
|---|---|---|---|---|
| Strait of Hormuz | 7 (7, 18, 110, 122, 68, 12, 3) | 340 | 8 | 2,262 facilities in 10–41 ms; whole answer 22–51 ms |
| Taiwan Strait | 6 (1,082, 1,894, 769, 174, 54, 1) | 3,974 | 7 | 3,925 facilities in 1,061–1,155 ms; whole answer ~1,180 ms |
| Port of Rotterdam | 5 (37, 80, 31, 9, 1) | 158 | 6 | 806 facilities in 5–30 ms |
| Netherlands (country) | 6 (79, 197, 114, 64, 7, 1) | 462 | 6 | 1,163 facilities in ~3 ms |
| Cobalt ore (item) | 7 (14, 8, 14, 98, 36, 17, 1) | 188 | 7 | 1,417 facilities in ~1 ms |

## Calling it from an agent

```python
import httpx
api = httpx.Client(base_url="http://localhost:8000")
sim = api.post("/simulate", json={"node_id": "47937", "base_branch": "main"}).json()
print(sim["kpis"], sim["latency_ms"])
api.delete(f"/branches/{sim['branch']}")   # clean up
```

### Strategic exercise rules

`POST /match` now defaults to `{base_branch: "main", rounds: 6, strategic: true, seed: 7}`.
`strategic: false` selects the original match rules. `seed` is an integer from 0 to 1,000,000.
RED disruption kinds have a two-turn cooldown. Strategic matches stream a BLUE preparation move at round 0, an initialization `inject`, and a clock
`inject` before each combat round. Clock moves contain replayable `game_tick` edits; BLUE move edits
contain `game_order` with the selected measure nested in `args`. The public move `action`/`args`
continue to describe the selected measure.

Moves additionally contain `strategy`: credits remaining/total, cost, ready round, pending orders,
completed recoveries/events, cumulative loss, priority programme capability/threshold, event status,
chosen planning preview and compared alternatives. Summaries additionally contain `strategic`,
`cumulative_loss` (percentage-point rounds), `average_loss_pct`, `round_scores`, `objective_met`,
and the final budget, pending orders and programme capabilities. Programme objectives are checked
at each combat round end. Replay reproduces orders, maturity, stock exhaustion and seeded events
without model calls. Recordings made before strategic rules continue to replay unchanged.
