# AGENTS.md - context for coding agents

Read this first. It is the map of the repo, the decisions already made, and the traps already hit, so a new
session does not have to re-explore. Deeper references are linked; only open them when the task needs it.

## What this repo is

EDTH x TuringDB hackathon pack (fork of `turing-db/turingdb-hackathon-defense`, remote `upstream`). Layers:

1. **Datasets** - seven prebuilt TuringDB 3.0 graphs under `graphs/` (supply_chain, supply_chain_deep,
   logistics_risk, drone_swarm, power_plants, poledb, attack_scenarios). Docs in `docs/<name>.md`;
   `scripts/generate_supply_chain_deep.py` is upstream's generator for the deep graph.
2. **`theatre`** - all seven fused into one graph by `fusion/` (426,969 nodes / 1.62M edges after the report
   commits), plus synthetic bridges and 21 intel `Report` nodes. **Generated, not in git** (its 3.0 store has
   a 106 MB file, over GitHub's limit): `uv run python fusion/build_theatre.py` (~2 min), or let the agents'
   supervisor build it on first use. Schema/queries: `docs/theatre.md` (deep layer: see below).
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
uv run python fusion/build_theatre.py        # once: builds graphs/theatre (~2 min), leaves a server running
uv run turingdb stop -turing-dir "$(pwd)"    # then restart in-memory so branches never touch disk:
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

Last known state (TuringDB 3.0, theatre with the deep layer): API + fusion + offline agents green;
UI 27 tests, typecheck and build OK. See the latest validation notes in docs/agents.md for live checks. Live tests skip themselves when the server or key is missing.

## TuringDB 3.0 - things that will bite you

Pinned to `turingdb==3.0`; upstream converted all bundled graphs to the 3.0 on-disk format.
3.0 lifted most 1.37 limits: `DISTINCT`, `WITH`, `collect`/`sum`/`avg`, grouped aggregates, `IN`,
`CONTAINS`, `OPTIONAL MATCH`, comma joins, variable-length paths (`-[:R]->+`, `-[:R]->{2,6}`), `|` edge
unions and `shortestPath` all work. What still bites:

- **Deleting a node with edges needs `DETACH DELETE`** (plain `DELETE n` errors).
- `edgeType(e)` is gone: use `type(e)`. **`labels(n)` returns a list** (`api/backends/turing_session.first_label`).
- Writes need a change: `client.new_change()` -> checkout -> queries -> `COMMIT`.
- **A client checked out on a change cannot `new_change()`**, and there is **no change-on-change**: every
  branch is cut from main (verified on 3.0).
- Naming a label/property that does not exist is an error, not 0 rows (`Session.labels` / `.property_types`).
- The importer added an `id` String property to every node of the source graphs (original node id).
- Changes are not persisted with `-in-memory` (by design here). A persistent server (what
  `fusion/build_theatre.py` starts) would write branches to disk - restart in-memory before running agents.
- `db.history()` `nodeCount`/`edgeCount` are per-commit deltas.
- No documented query cancel; the agents keep their watchdog (`runtime.guarded_query`).
- `agents/guard.py` still enforces the stricter 1.37-era rules (single linear MATCH, no DISTINCT/WITH/var-length).
  Safe but conservative; relax it deliberately if agents need deeper queries.
- Shell gotcha: never `pkill -f "turingdb start"` from a Bash tool call - the pattern matches the tool's own
  shell and kills it. Use `turingdb stop -turing-dir "$(pwd)"`.

## supply_chain_deep inside theatre

Fused by `fusion/assemble.py` + `fusion/links.py::add_deep_powered_by`:
- labels kept (Platform, System, Subsystem, Assembly, Subassembly, Component, Material, Mineral, Facility,
  Company, Port, Chokepoint, SeaArea, Disruption) except **`Shipment` -> `Consignment`** (avoids mixing with
  logistics_risk Shipments). Edge types kept (CONTAINS, PRODUCED_AT, SUPPLIES, OPERATED_BY, SUBSIDIARY_OF,
  SHIPS_VIA, SEA_LANE, SHIPPED_FROM/TO, CARRIES, TRANSITED, IMPACTED_BY, AFFECTS, PRODUCTION_SHARE, ...).
- `Country` merged by ISO3 into theatre's Country (adds region, nato_member, eu_member, eu_sanctions_target);
  HKG and VGB are new -> 170 Country nodes.
- Port/Chokepoint/SeaArea `lat`/`lon` renamed to `latitude`/`longitude` (`geo_method: reference_coordinates`).
- Facilities had only a city: placed from `fusion/deep_geo.py` (177 city centroids) + 6 km seeded jitter
  (`geo_method: city_centroid_jitter`, `geo_synthetic: true`). No Manchester facility exists in the deep data.
- `Facility -[:POWERED_BY {synthetic, distance_km}]-> PowerPlant`: 3 nearest within 50 km (12,406 edges;
  102 remote facilities have none).
- Fusion runs without the deep source too (unit-test fixtures).
- **Map**: `facility` and `port` are API node kinds (`api/models.py` Kind, `api/nodes.py`, `KIND_QUERIES`,
  `SNAPSHOT_KINDS`) and UI layers ("Facilities", "Ports" in the rail; drawn small because facilities cluster at
  city centroids). Ports and facilities are strikable (UI `STRIKABLE`). Strikes cascade into the deep layer:
  lost Port -> facilities that export through it (`SHIPS_VIA`), plant -> Facility via `POWERED_BY`, and a lost
  Facility puts its buyers at risk via `SUPPLIES` (`api/cascade.py` RULES; `TuringDependencies` special-cases
  `SUPPLIES` as an outgoing edge).
- **Scenario agent** considers the deep layer: `places(name=...)` also lists deep-facility cities and ports,
  `wipe_bbox` destroys Facility/Port too (`actions.WIPE_DEFAULT`), `propagate` flags facilities that lost power
  (`no_power`) or lost a supplier (`at_risk`), and `simulate_scenario` returns a `deep_supply` section
  (facilities destroyed/flagged/downstream, platforms exposed) that the UI panel shows. The old-layer loss is
  reported as `original_layer_supply_loss_pct`. Live-tested: Istanbul -> 34 destroyed, 96 flagged, 2,519
  downstream; Manchester has no deep facilities.
- **One-shot threat/defence agents stay on the original synthetic supply layer** (their impact model and actions).
  Retargeting the one-shot *threat* agent onto the deep network (real chokepoints/countries) was deliberately not done.

## The agents system (`agents/`)

Goal: agents explore alternative graph states in branches, evaluate, compare by diff, never modify main, and
run with no operator intervention.

| File | Role |
|---|---|
| `config.py` | env settings; `MODEL_PREFERENCE` (default `Qwen/Qwen2.5-72B-Instruct`) |
| `llm.py` | Featherless OpenAI-compatible client; JSON action parser (`parse_action`); gated-model fallback |
| `engine.py` | model-agnostic ReAct loop: one JSON action per turn `{"thought","action","args"}`, tools return JSON |
| `guard.py` | read-only Cypher guard: single MATCH linear path, no writes, auto `LIMIT` (1.37-era strictness) |
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

**Wargame / stacking (added by the repo owner, merged in).** `agents/match.py` (+ `match_board.py`,
`match_prompts.py`) runs a turn-based red-vs-blue match: each round red makes one disruption and blue one
countermeasure, each a branch stacked on the current head; operators can inject events (the scenario agent
runs on the head); matches are saved to `matches/<id>.json` and can be replayed. Stacking without
change-on-change: `tools.build_stacked` replays `lineage_actions(parent)` + the new actions + `propagate` into a
fresh change. The scenario agent's `simulate_scenario` takes a `parent` (main or a wargame head).
`api/jobs.py` + `api/agent_hub.py` run agent calls as background jobs streamed over SSE
(`/agent/jobs/<id>/events`, `/match/...`); `api/env.py` loads a gitignored `.env` (`OPSMAP_BACKEND`,
`FEATHERLESS_API_KEY`) without overriding real env vars. UI: Wargame panel (`WargamePanel.tsx`, `state/wargame.ts`,
`LossChart`, `MoveFeed`, `BranchTree`, `map/matchLayers.ts`).

**Deep wargame (distinct from the one-shot agents).** `deep_impact.py` loads main's deep network once and
reads branch state, then evaluates capability in Python; `deep_actions.py` registers replayable typed edits;
`match_deep.py` combines scores and builds map effects. Match loss = `DEEP_WEIGHT = 0.75` deep platform
capability loss + 25% original parts loss (legacy-only fallback without the deep graph). Each move includes
`breakdown {deep_pct, legacy_pct}`; the UI feed shows both. Relative match loss subtracts the base score.
- Facility output: zero if removed/closed or if all its original power feeds are lost; otherwise best export
  route. Closed ports retain `OVERLAND_FLOOR = 0.4`; alternative ports have `ALT_PORT_EFFICIENCY = 0.8`;
  blocked chokepoints lose `REROUTE_LOSS = 0.35` times their shipment share (combined shares capped at 1).
- Item production is share-weighted maker output (deleted makers keep their original lost share in the
  denominator, including when all PRODUCED_AT edges vanish). Availability is the minimum of production and buffered
  child availability: `1 - (1 - child) * (1 - TIER_BUFFER)`, `TIER_BUFFER = 0.3`. Country export controls zero
  that country's makers and production share for the item. Stockpiled items retain `STOCKPILE_FLOOR = 0.8`.
- Platform weights: `EQUAL_SHARE = 0.5` equal programme share + 50% annual-value share (demand x cost).
  All constants are gameplay assumptions, not calibrated. Mineral controls are weak after seven buffers.
- Red: `close_port`, `block_chokepoint`, non-allied `export_controls`, `facility_outage`; blue:
  `reroute_exports` (up to three ports), `replace_facility`, `second_source` (allied first, share 50),
  `stockpile`, `harden`. Candidates preview the current head's effects. Red cannot repeat its previous
  action kind; rejected fallbacks try alternates. Prompts retain two candidates per kind without truncating
  JSON, and encourage at least three useful disruption kinds across a multi-round exercise. One-shot
  threat/defence actions are unchanged. `match_errors.py` shares MoveRejected across CLI/imported modules.
- Deep effects flash/pulse ports, facilities and chokepoints, with arcs to affected exporters and platform
  final-assembly facilities. They use capability changes rather than only ordinary node diffs.
- `Session.refresh_schema()` is required after lineage edits introduce new properties. Numeric edge
  properties must be emitted as numeric literals (`BranchLab.add_edge`), and NATO/EU flags may be numpy bools.
- Offline rules: `test_deep_impact.py`, `test_match.py`; live moves/replay with fake model:
  `test_match_live.py`. See `docs/agents.md` for the model and demo commands.


## OpsMap integration

- `api/backends/turing.py::_describe_change` recognises `AgentBranch` -> `Branch.kind` threat|defence|scenario
  (`BranchKind` extended in `api/models.py` and `ui/src/api/types.ts`). `discard` allows strike + agent kinds;
  hypotheses stay read-only.
- `api/agent_routes.py` (mounted in `api/main.py` only when backend == turingdb; failure to mount is logged,
  never fatal): `GET /agent/status`, `POST /agent/scenario {question,max_steps}`, `/agent/threat`,
  `/agent/defence {threat_branch}`, `/agent/redblue`. Calls run as background jobs with SSE progress.
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
- Featherless: first call to a model can take ~60 s (cold start), warm calls ~2-6 s.
- The Featherless plan allows 4 concurrency units = ONE 72B request at a time. A second concurrent caller
  (another session, a local run, a parallel test) gets HTTP 429 "Concurrency limit exceeded"; `llm.py` waits it
  out on a separate path (honours Retry-After, up to `RATE_LIMIT_PATIENCE_S` = 150 s); other errors get
  `MAX_RETRIES` = 5. Do not run agent tests in parallel with a live agent run. `meta-llama/*` models are
  gated (403) for this account; `llm.py` falls through to the next model automatically.
- Background processes: shell `&`/`nohup` do not survive between tool calls here; use the Bash tool's
  `run_in_background`. Background jobs are killed at their timeout (the uvicorn server was killed that way).
- Starting the DB reliably from a script: `Supervisor(...).ensure_running()` (builds `graphs/theatre` if
  missing, starts in-memory, clears stale `turingdb.lock` / `.sock` on restart). Clear leftover changes: checkout each id from `CHANGE LIST` and run `CHANGE DELETE`.
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
- 3.0 rejects expressions nested deeper than 256 levels, so `id_clauses` chunks at `ID_CHUNK = 200`. Keep OR
  chains: `n IN [...]` works but scans (~2 s for 3,000 ids vs ~40 ms for OR chunks).

## Conventions

- Match surrounding code: short module docstrings explaining *why*, typed Python 3.11, `from __future__ import
  annotations`, dataclasses, no new dependencies without reason (`httpx` was added to main deps on purpose).
- Agent-written Cypher always goes through `guard.check_read_query`; writes only through `actions.py`.
- Keep `main` of the graph untouched: never `CHANGE SUBMIT` from agent code.
- Git: work on `claude/supply-chain-threat-defence-3gi0qk`; it is pushed, no PR opened yet (user is testing
  locally first). `upstream` = turing-db/turingdb-hackathon-defense (merged up to `a87d58b`). Do not commit
  runtime dirs or `graphs/theatre/` (all gitignored; `uv.lock` IS tracked).

## Strategic wargame handoff (3 October 2026)

Implemented after reviewing the repetitive red/blue match: finite resources, delayed recovery,
capacity constraints, preparation, disruption variety, opponent previews, seeded events, programme
objectives and cumulative scoring. Full rules and assumptions: `docs/agents.md`; API: `docs/api.md`.
Changes are saved in this working tree, **not committed or pushed**. Preserve existing user changes,
including match export/download work, when continuing. The one-shot threat/defence agents retain their
original model; these rules apply to the strategic turn-based match.

### Where the new behaviour lives

- `agents/game_rules.py`: replayable `game_init`, `game_order`, `game_tick`, dispatched through
  `agents/actions.py`. Blue has **14 credits total, including preparation**. Rerouting costs 2 and is
  immediate; replacement production costs 5 and takes two rounds; second sourcing costs 3 and takes
  two rounds; stock costs 2 and lasts two combat rounds; hardening costs 3 and takes one round.
  Orders charge once; pending duplicates are rejected. Failed completion still consumes its cost.
  **GameState payload is base64-encoded JSON**: raw JSON strings are corrupted by the Cypher string
  literal helper. Preserve this encoding, including Unicode and embedded quotes.
- `agents/deep_impact.py`: strategic port capacity is based on original exporter count (1.25x,
  minimum two slots); overload reduces exporter output. New qualified production uses 20 percentage
  points of maker spare utilization per item, and overcommit penalizes output. Replacement plans consume
  capacity sequentially. Hardening gives partial resilience, not immunity; power/shipping constraints
  still apply. Recordings without GameState keep classic scoring. Constants are gameplay assumptions,
  not calibrated forecasts.
- `agents/deep_actions.py`: proactive candidates and high-share programme assembly makers are included
  even when a platform has multiple makers. Selecting only sole makers previously buried useful facility
  disruptions beneath heavily buffered inputs. Already closed facilities are excluded.
- `agents/strategic_board.py`: match-local wrapper around `LabBoard`. Up to three distinct candidate
  kinds are tested in temporary real branches against one plausible opponent reply and up to two
  rounds of clock advancement, capped at the match horizon. Production disruptions are included when
  available. Preventive stock/source candidates require measured benefit against hypothetical disruptions.
  Budget, pending orders and readiness are enforced. Preview branches are discarded. Blue forecasts
  advance the clock before choosing the next red reply and respect the red action-kind cooldown.
  This is bounded lookahead, not exhaustive minimax.
- `agents/match.py` / `match_prompts.py`: Blue preparation at round 0; red action kinds cannot repeat
  either of the previous **two red turns**. Before combat rounds, ticks resolve orders and events.
  Seed 7 triggers a 20% export-capacity reduction in round 4 of a six-round match, lasting two rounds.
  Three eligible priority programmes must remain at least 80% capable at each round end. Cumulative
  relative loss adds half the loss after red plus half after blue per combat round; late recovery cannot
  erase earlier exposure. Partial-round averages use observed half-round duration. Scores update before
  SSE/save. When wait is the only legal blue move, it is automatic and uses no model call.
- `agents/llm.py`: malformed HTTP-200 provider JSON is retried without logging provider payloads.
  Exhausted response errors use a marked legal match fallback; missing credentials/provider unavailability
  still report an error. Do not run real-model callers concurrently (Featherless concurrency limit).
- `agents/match_board.py`: unwraps ordered actions and combines tick recovery/degradation map effects;
  rule/tick branches have defence markers, avoiding fake scenario bases.
- `agents/match_export.py`: readable Markdown transcript and strategy details. This file was already
  untracked user work when this task began; preserve the download/export functionality.
- UI: `WargamePanel.tsx`, `MoveFeed.tsx`, `state/wargame.ts`, store/types/lib/CSS show credits,
  deadlines, objectives, events, compared alternatives and cumulative results. Saved replay has
  **1x / 4x / 20x** speeds and rebuilds graph branches without LLM calls; DB rebuild time still applies.

### Defaults, validation and demo

- UI/API and CLI default to six-round strategic games. `Match(... strategic=False)` remains the Python
  compatibility default; CLI `--classic` opts out and `--seed` controls the deterministic event.
- Latest focused Python verification: **137 passed, 7 skipped** with
  `.venv/bin/python -m pytest tests/agents/test_guard.py tests/agents/test_llm.py tests/agents/test_deep_impact.py tests/agents/test_match.py tests/agents/test_game_rules.py tests/api -q`.
  UI: **28 tests passed**, typecheck and build passed; `git diff --check` clean. These are focused checks,
  not a rerun of every repository test.
- `tests/agents/test_game_rules.py` covers budgets, delays, expiry, events, encoding, capacity,
  hardening, forecasts, cooldown and candidate selection. `test_match.py` covers forced waits,
  partial-round scoring and legal provider-error fallbacks; `test_llm.py` covers malformed provider JSON.
- `tests/agents/test_strategic_live.py` uses a deterministic model with real TuringDB, checking a
  four-round match and replay, identical final state/loss, discarded previews and unchanged main.
  Earlier live suites passed (22 checks); some later refinements were verified by focused offline checks
  and the subsequent real-model demo/browser replay, rather than rerunning that entire live suite.
- Real Qwen six-round demo: `matches/strategic-demo.json`, transcript `matches/strategic-demo.md`.
  Match id `d7e8d138`, seed 7, **zero fallbacks**, final loss **39.0%**, average **31.4%**, cumulative
  **188.1 percentage-point rounds**, 13/14 credits spent. Red used port closures, facility outages and
  chokepoints. Blue prepared, rerouted, ordered replacement production ready two rounds later, hardened
  another facility, then had to wait. Priority objectives were breached. Browser replay completed with
  the same result and visible score/branch/move cards.
- Match JSONs and generated graph stores are runtime artifacts; do not commit them. Some match files are
  untracked rather than ignored in this checkout. Do not delete other users' matches or ephemeral branches
  indiscriminately. Branch IDs and local server PIDs are transient; discover current state before reuse.

## Open items / ideas

- Validated 3 October 2026: full Python suite 197 passed (real Featherless included); subsequent deep/match
  checks 39 passed; UI 27 tests, typecheck/build passed. Demo: four real-model rounds, final combined loss
  22.5% (deep 30.0%, parts 0.0%), no fallbacks; browser replay completed.

- UI eyeballed with Playwright screenshots (facility/port layers, scenario branch overlay, Scenario panel);
  the online CARTO basemap fails TLS in this sandbox, so screenshots show the built-in outline fallback.
- Defence often prefers one bulk measure; if a "three distinct countermeasures" story is wanted, constrain it
  in `defence.py`'s prompt or budget.


## Featherless Simple Jev Blue handoff (3 October 2026)

- `agents/jev.py` is a separate authenticated `/v1/classifier` client using `httpx` and the existing
  `FEATHERLESS_API_KEY`. Production only: the operator explicitly declined keyless demo switching.
- Default classifier: `featherless-ai/gemma-4-26B-A4B-classifier`. Authenticated repository smoke passed:
  selected the critical-part backup candidate, 1,758.2 ms. Qwen3.8-27B, Qwen3.6-35B-A3B and Qwen3.5-4B
  returned HTTP 400 in tested requests; Gemma returned 200 with the same key. Do not describe this as
  a general connection failure or claim Qwen works because it appears in the model catalog.
- `agents/blue_selection.py` shares Blue proposal/selection across standalone defence and wargames.
  LLM proposes at most five alternatives; Python validates them in temporary branches and discards
  previews; Jev selects a locally stored candidate ID; Python executes and measures; the LLM explains.
  Jev does not calculate loss or produce explanation text. Preserve one Blue action per turn.
- `BLUE_JEV_ENABLED=1` opts in; default remains off. `BLUE_JEV_MODEL`, `BLUE_JEV_TIMEOUT`,
  `BLUE_JEV_MIN_CONFIDENCE` and `BLUE_JEV_PRIORITIES` are documented in `.env.example` and `docs/jev.md`.
  Default threshold 0 accepts valid choices; probabilities are conditional on options, not correctness.
  Invalid selection, timeouts and service errors use existing Blue. Never silently change model/service.
- Bounds: one proposal chat HTTP attempt (30-second network-phase timeout), at most five graph previews,
  one classifier request (15-second network-phase timeout by default), one explanation chat attempt.
  Existing ordinary chat retries remain unchanged. No strict total wall-clock deadline is claimed.
- `agents/defence.py`, `agents/orchestrator.py` and `agents/match.py` integrate the selector. Existing
  guards, action contracts, branch stacking, lineage and propagation remain; never submit to main.
  Match/job telemetry stores candidates, selection, probabilities, durations, fallback, measured impact
  and logical/HTTP chat counts. MoveFeed and the one-shot panel show concise selection summaries.
- Offline tests: `tests/agents/test_blue_selection.py`, bounded call coverage in `test_llm.py`.
  `tests/agents/test_jev_live.py` uses deterministic provider doubles with real TuringDB for cleanup,
  replay, unchanged main and optional strategic budget/one-action rules. Two graph tests passed in
  the working tree; the strategic extension remains separate pre-existing uncommitted work.
- Latest working-tree focused validation: 152 Python passed / 7 skipped; UI 28 passed, typecheck/build passed.
  Serial real-Qwen comparison started at 4.4% supply loss: both existing Blue and opt-in fallback ended
  at 0.0% with one countermeasure. Existing: 6 chat calls, 155.36 s; fallback: 7 chat calls + 1 classifier
  attempt (756.4 ms), 100.61 s. This is no Jev improvement claim. Full live Gemma hybrid-match quality
  remains unmeasured. Runtime comparison files under `logs/jev-validation` must not be committed.
- Connection check: `.venv/bin/python -m agents.jev --smoke`. Never print keys/provider bodies.
  Official current production API: https://featherless.ai/docs/api-reference-classifier.

- Jev-only commit snapshot independently verified against HEAD without the uncommitted strategic
  extension: 134 Python passed / 9 skipped and UI typecheck passed. Runtime artifacts are excluded.
