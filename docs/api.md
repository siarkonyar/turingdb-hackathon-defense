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

## Calling it from an agent

```python
import httpx
api = httpx.Client(base_url="http://localhost:8000")
sim = api.post("/simulate", json={"node_id": "47937", "base_branch": "main"}).json()
print(sim["kpis"], sim["latency_ms"])
api.delete(f"/branches/{sim['branch']}")   # clean up
```
