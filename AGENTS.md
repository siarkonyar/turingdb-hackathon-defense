# AGENTS.md - context for coding agents

Read this first. It is the map of the repo, the decisions already made, and the traps already hit, so a new
session does not have to re-explore. Deeper references are linked; only open them when the task needs it.

## What this repo is

EDTH x TuringDB hackathon pack. Three layers, built in this order:

1. **Datasets** - six prebuilt TuringDB graphs under `graphs/` (supply_chain, logistics_risk, drone_swarm,
   power_plants, poledb, attack_scenarios). Per-dataset docs in `docs/<name>.md`.
2. **`theatre`** - all six fused into one graph (294,200 nodes / 845,561 edges) by `fusion/`, plus synthetic
   bridges and 21 intel `Report` nodes. Schema, example queries and 1.37 caveats: `docs/theatre.md`.
3. **OpsMap** - FastAPI backend (`api/`) + React/MapLibre/deck.gl map (`ui/`) over `theatre`: strike
   simulation, branch diff, hypotheses, time replay. Contract: `docs/api.md`.
4. **LLM agents** (added on branch `claude/supply-chain-threat-defence-3gi0qk`, commit `77fc806`) - threat,
   defence and scenario agents that use **TuringDB branches as their search space**. Full write-up:
   `docs/agents.md`. Summarised below.

## Layout

```
agents/        LLM agents (Featherless AI + TuringDB branches)          <- new
api/           OpsMap FastAPI; api/agent_routes.py mounts /agent/*      <- agent_routes new
ui/            OpsMap UI; ui/src/components/ScenarioAgent.tsx           <- ScenarioAgent new
fusion/        builds theatre (flat imports, run as scripts)
graphs/        prebuilt graph stores (do not edit by hand; ~350 MB)
docs/          dataset docs, theatre.md, api.md, agents.md
tests/         api/, fusion/, agents/  (pytest, pythonpath=".")
skills/        bundled TuringDB Claude Code skills (Cypher dialect notes: skills/turingdb/*.md)
```

## Run

```bash
uv sync && npm --prefix ui install
uv run turingdb start -turing-dir "$(pwd)" -demon -in-memory -load theatre -start-timeout 20000   # :6666
OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app --port 8000      # live API (+ /agent/* routes)
npm --prefix ui run dev                                              # http://localhost:5173
uv run python -m agents.orchestrator                                 # threat -> defence, prints headline
uv run python -m agents.orchestrator --scenario "A catastrophic event has destroyed everything across Manchester..."
```

Without `OPSMAP_BACKEND=turingdb` the API serves mock fixtures (`api/mock/`), the UI shows "MOCK FIXTURES",
and the agent routes / Scenario button are absent.

## Tests

```bash
uv run pytest tests/agents/test_guard.py tests/agents/test_llm.py -q   # offline, <1 s
uv run pytest tests/api -q                                             # mock + live (live skips w/o server)
uv run pytest tests/agents/test_branch_lab_live.py -q                  # live TuringDB, no LLM, ~1 min
uv run pytest tests/agents/test_agents_live.py -q                      # real Featherless + TuringDB, ~8 min
npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build
```

Last known state: all of the above green (77 passed for agents-offline + branch-lab + api; 4/4 live agent
tests; UI 16 tests, typecheck and build OK). Live tests skip themselves when the server or key is missing.

## TuringDB 1.37 - things that will bite you

Pinned to `turingdb==1.37`; 3.0 cannot load the bundled graphs ("File outdated"). Do not upgrade.

- **Comma-joined patterns sharing a variable return wrong rows or hang the server forever.** Use single
  linear paths: `(a)-[:R]->(b)<-[:S]-(c)`. Exception that works: `MATCH (a), (b) WHERE a = 1 AND b = 2
  CREATE (a)-[:R]->(b)` (two id-bound nodes, used to add edges).
- **No query cancel / timeout**, and `turingdb stop` waits for a runaway query -> `kill -9`.
- Not supported: `OPTIONAL MATCH`, `WITH`, `UNWIND`, `DISTINCT`, `collect`, `sum`/`max`, grouped aggregates,
  `IN`, `CONTAINS`/`STARTS WITH`, string `<`/`>`, `|` in edge types, `CALL db.procedures()`. Aggregate in pandas.
- `type` and `new` are reserved: write ``n.`type` ``.
- Naming a label/property that does not exist is an **error**, not 0 rows (check `CALL db.labels()` /
  `CALL db.propertyTypes()` first; `Session.labels` / `.property_types` cache these).
- Writes need a change: `client.new_change()` -> checkout -> queries -> `COMMIT` (needed between node and
  edge creates, and after `DELETE` before the change's own reads see it). `DELETE n` removes incident edges.
- **A client checked out on a change cannot `new_change()`** ("Cannot create a new change while working on
  one"), and there is **no change-on-change**: every branch is cut from main.
- Changes are not persisted with `-in-memory`; they vanish on server restart (by design here).
- Node ids are internal integers, stable across main and changes (diffs compare by id).
- Time filters use `ts_epoch` (int), not ISO strings.

## The agents system (`agents/`)

Goal: agents explore alternative graph states in branches, evaluate, compare by diff, never modify main, and
run with no operator intervention.

| File | Role |
|---|---|
| `config.py` | env settings; `MODEL_PREFERENCE` (default `Qwen/Qwen2.5-72B-Instruct`) |
| `llm.py` | Featherless OpenAI-compatible client; JSON action parser (`parse_action`); gated-model fallback |
| `engine.py` | model-agnostic ReAct loop: one JSON action per turn `{"thought","action","args"}`, tools return JSON |
| `guard.py` | read-only Cypher guard: single MATCH linear path, no writes, auto `LIMIT`, rejects 1.37-unsupported syntax |
| `runtime.py` | `Supervisor` (auto start / kill+restart server), `Graph` (sessions, `guarded_query` watchdog) |
| `impact.py` | **the objective**: projected supply-chain loss from graph state |
| `branches.py` | `BranchLab`: open / evaluate / keep / discard branches, ledger + replay after restart, diffs |
| `actions.py` | typed edits applied inside a branch (attacks, defences, scenario wipe/propagate) |
| `tools.py` | shared tools (schema, query, impact, list_branches, diff) + `build_branch` |
| `threat.py` / `defence.py` / `scenario.py` | the three agents (system prompt + tools) |
| `orchestrator.py` | `Lab.create()`, `run_red_blue()`, `run_scenario_question()`, CLI |

**Impact model.** Demand = every (Site, Part) pair with POs, weight = PO count x criticality (A=5, B=2, C=1),
read from main once. On a ref: part supplier works iff it exists + has >=1 `POWERED_BY` + >=1 `SOURCES_FROM`;
part available iff >=1 working `SUPPLIED_BY` supplier; site works iff exists + powered. `loss = 1 -
satisfied/total`. Baseline on main = 0%. Every part has exactly one supplier in the data (300 parts / 40
suppliers), so supplier loss is the main lever; one plant strike usually = 0% (sites have 3 feeds).

**Branches.** Each carries an `(:AgentBranch {role, label, parent, spec})` marker. `role` in
threat|defence|scenario; `spec.actions` is the replayable action list. A **defence branch is cut from main
and replays the threat's attack actions, then its countermeasures** (because no change-on-change), so it is
directly comparable to the threat branch. `parent` is lineage only.

**Actions** (args tolerate aliases via `_pick`, e.g. `gppd_idnr`/`plant_gppd`, `site_id`/`facility_id`):
- threat: `strike_supplier{supplier_id}`, `strike_plant{gppd_idnr}`, `cut_route{supplier_id}`
- defence: `backup_all_affected_parts{only_critical?}` (strongest), `add_backup_supplier{part_id}`,
  `reroute_supplier{supplier_id}`, `restore_power{facility_id}`, `prioritise_air_defence{gppd_idnr}`
- scenario: `wipe_bbox{west,south,east,north,labels?}`, `propagate{}`
- Threat targets are deliberately limited to supply infrastructure (suppliers, plants, routes) and framed as
  abstract node removal - keep it that way (no operational attack content, no real-world targeting).

**Orchestrator selection.** `run_red_blue` picks the threat's `worst_branch` (else max-loss threat branch)
and the **lowest-loss defence branch** whose `spec.parent` is that threat (the agent's own pick only if it is
as good). Headline: `"N countermeasure(s) reduce the projected loss from X% to Y% (summary)"`. Last real run:
20.2% -> 0.0% with `backup_all_affected_parts`; an earlier run without that action reached 13.9% -> 8.1%.

**Scenario agent.** Tools: `places` (Site.place / Supplier.place with coords - place names are not
queryable, so this is how "Manchester" -> SITE01 Trafford Park 53.47,-2.31), `query`, `preview_region`,
`simulate_scenario` (wipe + propagate in a new branch, returns diff payload), `diff`, `impact`. Manchester
result: ~27 located nodes destroyed (6 plants, 20 drones, SITE01), 13.8% supply loss.

## OpsMap integration

- `api/backends/turing.py::_describe_change` recognises `AgentBranch` -> `Branch.kind` threat|defence|scenario
  (`BranchKind` extended in `api/models.py` and `ui/src/api/types.ts`). `discard` allows strike + agent kinds;
  hypotheses stay read-only.
- `api/agent_routes.py` (mounted in `api/main.py` only when backend == turingdb; failure to mount is logged,
  never fatal): `GET /agent/status`, `POST /agent/scenario {question,max_steps}`, `/agent/threat`,
  `/agent/defence {threat_branch}`, `/agent/redblue`. Endpoints are sync (FastAPI threadpool) and slow (LLM).
- UI: bottom-bar **Scenario** button (live only) -> `ScenarioAgent.tsx` -> `askScenario()` in
  `state/actions.ts` -> `refreshBranches()` + `switchBranch(branch)`. The map overlay comes from the existing
  `GET /diff main->branch` (`overlayFromDiff`: removed = red/lost, changed status = amber). Branch switcher has
  Threat / Defence / Scenario groups.
- `/diff` snapshots only `plant, site, supplier, drone, report, part` - destroyed Locations/Crimes/Persons do
  not appear in it (they are real deletions, just not in the snapshot).

## Environment (cloud session specifics)

- `FEATHERLESS_API_KEY` is an environment secret. Never print, log or hardcode it. `api.featherless.ai` had to
  be allowed in the environment's network policy (done); if a 403 `connect_rejected` comes back, it is the
  policy again, not the key.
- Featherless: first call to a model can take ~60 s (cold start), warm calls ~2-6 s. `meta-llama/*` models are
  gated (403) for this account; `llm.py` falls through to the next model automatically.
- Background processes: shell `&`/`nohup` do not survive between tool calls here; use the Bash tool's
  `run_in_background`. Background jobs are killed at their timeout (the uvicorn server was killed that way).
- Starting the DB reliably from a script: `Supervisor(...).ensure_running()` (clears stale `turingdb.lock` /
  `.sock` on restart). Clear leftover changes: checkout each id from `CHANGE LIST` and run `CHANGE DELETE`.
- Scratchpad for temp files: the session scratchpad dir, not `/tmp`.

## Traps already hit (do not repeat)

- **Never add `tests/agents/__init__.py`**: pytest then imports `tests/agents` as top-level `agents` and
  shadows the real package. Test dirs here have no `__init__.py`.
- Supplier keys are source-prefixed (`supply_chain:SUP012`, `logistics_risk:P0023_S1`); `_resolve` accepts the
  bare id too.
- Only **part suppliers** (`source = 'supply_chain'`) and Sites have `POWERED_BY`. Logistics suppliers (3,524)
  never do - do not flag them as unpowered.
- `n.prop <> 'x'` is NULL (excluded) when the prop is unset; compute sets in Python instead.
- A stray half-written `agents/lab.py` once appeared (from an interrupted turn) and was deleted; if it shows
  up again, it is junk - nothing imports it.
- `Session.q` wraps every SDK error in `QueryFailed` (502); the message's last line has the TuringDB reason.

## Conventions

- Match surrounding code: short module docstrings explaining *why*, typed Python 3.11, `from __future__ import
  annotations`, dataclasses, no new dependencies without reason (`httpx` was added to main deps on purpose).
- Agent-written Cypher always goes through `guard.check_read_query`; writes only through `actions.py`.
- Keep `main` of the graph untouched: never `CHANGE SUBMIT` from agent code.
- Git: work on `claude/supply-chain-threat-defence-3gi0qk`; it is pushed, no PR opened yet (user is testing
  locally first). Do not commit runtime dirs (`data/`, `logs/`, `*.lock`, `*.sock` are gitignored).

## Open items / ideas

- UI Scenario panel not yet eyeballed in a browser (only typecheck/build/unit tests).
- Agent endpoints are synchronous and can take minutes; a job queue + progress polling would improve UX.
- Defence often prefers one bulk measure; if a "three distinct countermeasures" story is wanted, constrain it
  in `defence.py`'s prompt or budget.
