# Dover resilience exercises

A focused demo over the isolated `dover` graph (see `docs/dover.md`). A map-side chat panel offers exactly three
exercises. Each one applies a disruption in a TuringDB branch, reveals the impact one dependency degree at a time,
lets one recovery agent compare prepared recovery plans, executes the chosen plan in a separate recovery branch,
and reports measured before/after results.

All organisations, capacities, demands, stocks and timings are **fictional exercise assumptions** from the
generator. Nothing here is a calibrated forecast, and there is no targeting or weapon-effect model.

## The three exercises

| Suggestion | Scenario id | Event | Window |
|---|---|---|---:|
| Close the Dover Strait to shipping | `scenario:strait_closure` | Dover maritime-access node closed | 72 h |
| All ten Kent grid supplies fail | `scenario:kent_power` | Ten Kent `PowerPlant` grid supplies disabled | 48 h |
| London and Croydon lose critical infrastructure | `scenario:london_loss` | 114 facilities, grids, stockpiles and resource pools **destroyed** | 168 h |

The initial failures are the Scenario node's own `DISABLES` edges, read from the graph; the window is its
`duration_hours`. Any other scenario id is rejected (`UnsupportedExercise`, HTTP 422). There is no general
scenario generation.

## Demo procedure

```bash
.venv/bin/python -m datasets.dover.build --load    # once: import the dover graph on port 6667
.venv/bin/python scripts/run_dover_demo.py          # in-memory server, API on 8001, map on 5174
```

Open http://127.0.0.1:5174. The **Recovery agent** panel opens on the right (toggle it from the bottom bar). For
each suggestion:

1. The chat shows the disruption branch and its headline: essential demand, unmet cargo, capabilities below 80%.
2. The shared impact stepper (`CascadeStepper`) reveals affected facilities, ports and routes by **dependency
   degree**. Continue / Back / Show all work as in the Impact panel; the map pulses every initial failure.
3. The chat lists the important dependency paths and any unavailable alternatives.
4. The recovery agent's steps stream in (inspect, list, compare, execute), then the report appears.
5. **Show recovery on map** swaps the cascade layers for the recovery overlay; **Back to dependency cascade**
   returns.

`FEATHERLESS_API_KEY` (in `.env`) enables the model. Without it, or when the provider fails, the report shows the
prepared deterministic plan with a **FALLBACK** label and the reason.

The server must run in memory (`-in-memory`, as the launcher does): exercise branches are ephemeral and must not
be written into `data/dover-runtime`. Run one exercise at a time; the API accepts one run at a time (HTTP 429
otherwise), and the Featherless plan allows one concurrent request.

## Simulation rules (`agents/resilience/`)

| Module | Responsibility |
|---|---|
| `network.py` | Immutable network loaded from the generator (offline) or from TuringDB main (live); both produce identical data |
| `exercises.py` | The three exercises, their event kind and window |
| `availability.py` | Service availability over `DEPENDS_ON` at one instant |
| `cargo.py` | Daily cross-border cargo split under shared capacity |
| `plans.py` | Typed recovery actions, validation and static pool allocation |
| `simulate.py` | Time-stepped measurement of an exercise under a plan |
| `candidates.py` | Prepared, validated, measured candidates; unavailable-route checks |
| `explain.py` | Dependency degrees, key paths, before/after states, per-action benefit, map links |
| `agent.py` | The bounded recovery agent and its typed tools |
| `lab.py` | Disruption and recovery branches in TuringDB, read-back verification, replay |

### Dependencies

`DEPENDS_ON` is authoritative (consumer → provider). A node's availability is its physical availability times
the minimum over its dependency groups:

- **Required groups** (electricity, communications, water, crossing, terminals, last mile, aircraft, sea access,
  service, …) take the minimum of their providers: every group must be satisfied.
- **`material_input`** is a share-weighted mixture, `Σ share × provider / Σ share`. A missing provider keeps its
  share in the denominator, so a distribution centre that loses its 60% import keeps 40% from local production.
- `SUPPLIES` is used only for display (it is the projection the Plan A impact viewer uses); its severity is never
  reused as utility, service-time or readiness measurement.

### Time

The window is cut into segments wherever something changes: day boundaries, action readiness, generator fuel
end and reserve-release end. Each segment runs an operability pass (cargo assumed present), the daily cargo
split, then a final pass with delivered cargo, generator-fed loads and released stock. Demand fulfilment, cargo
and capability results are time-weighted over the window. Simulation time and dependency degree are separate:
degrees come from the graph and are revealed in the stepper; hours come from the simulator and drive the report
chart and readiness times.

### Cargo and shared capacity

Every consignment departs once a day. Cargo is split over usable routes, priority 1 first, then shortest deadline,
then cold chain. One daily ledger holds every shared limit, so a tonne is reserved on all of them at once:

- the route's `capacity_tonnes_day`, shared by both directions and all products;
- each terminal's handling (`handling_tonnes_day` for ports, `throughput_tonnes_day` for tunnel/airport
  facilities), shared by every route using it. The tunnel is therefore capped at **200 t/day** by its terminals,
  not its 320 t/day rating;
- each last-mile road hub's `throughput_tonnes_day`;
- for air, the departing pool's `available_units × payload_tonnes × rotations_day` (64 t/day). Rotations are
  counted on consolidated loads: at most four per pool per day.

A route is usable only while its own dependencies are available: terminals, power, communications, fuel, last
mile, aircraft and sea access. Arrival = departure + handling (`CAN_USE.handling_hours`) + `transit_hours`;
departure waits for the route's activation. Cargo arriving by its deadline is on time, later cargo is delayed,
and cargo that cannot arrive within the window is unmet. Domestic road legs are not timed, because the graph has
no calibrated road travel times. Daily demand counts as met when that day's cargo arrives by its deadline.

### Recovery actions

Each action names a real `RecoveryOption` attached to its target by `HAS_RECOVERY`; activation and duration are
the option's own `activation_hours` and `duration_hours`.

| Action | Option kind | Rule |
|---|---|---|
| `reroute` | `reroute_<route>` | Opens an independent route for all cargo, or only cargo due within 24 h (`short_deadline`) |
| `islanded_power` | `islanded_generation` | One generator (`provided_mw`) feeds named loads in its town; total load MW must fit |
| `mobile_power` | `mobile_power` | One generator feeds one facility |
| `release_stock` | `release_stock` | The product reserve fills a service's supply gap at up to daily demand for 48 h |
| `relocate` | `relocate_service` / `second_source` | A destroyed service or programme continues at a surviving receiving site |
| `second_source` | `second_source` | A destroyed export input is replaced from a producer's spare output |

### Conservation (never double-counted)

- **Generators**: per emergency reserve, `Σ consumes_generators ≤ mobile_generators` (3); a load is never fed twice.
  Runtime is limited to the reserve's `generator_fuel_hours` (interpreted as 72 h per generator). Fuel use is
  reported.
- **Provider spare**: `spare_tonnes_day` (producers) or the option's `provider_spare_tonnes_day` is one pool per
  provider, shared by every action that draws on it.
- **Receiving programmes**: `spare_service_people` is consumed per relocated programme (100), so one receiving
  site takes one programme.
- **Stock**: drawn down sequentially and never below zero. Cold-chain stock is released only from powered
  storage. A reserve stored at a destroyed facility is unusable.
- **Demand** is counted once. Displaced demand of a destroyed service counts only through a validated transfer,
  at the receiving site's own availability.

### Scenario-specific rules

- **Strait closure** disables the Dover maritime-access node, which closes both Dover sea routes
  (`sea_access`). The tunnel, Newhaven–Dieppe and both air routes stay open. Air is capped at 64 t/day per route,
  so independent capacity (568 t/day) cannot replace 1,084 t/day of baseline freight.
- **Kent grid outage** takes down substations, then communications, water, fuel handling, terminals and the Dover
  port. Each alternative route is judged by its own dependencies: the tunnel (Folkestone terminal and road hub) and
  Ashford–Beauvais air (Ashford airport and road hub) are **unavailable**; Newhaven–Dieppe and London–Paris air
  remain. Generators restore named loads only; they never re-energise a whole substation.
- **London loss** destroys facilities, grid supplies, stockpiles and resource pools. Continuity options never
  rebuild an asset (`restores_destroyed_asset = false`). Destroyed services relocate to surviving receiving sites
  (the option's provider town). The London aircraft pool and airport are lost, so London–Paris air is unavailable.
  London's destroyed export inputs can be second-sourced from other UK regions. Nothing is delivered to a
  destroyed facility.

### Prepared candidates

Candidates are built from the graph's options, validated, and measured before the agent sees them. Rejected
actions are dropped with their reason and listed as excluded.

| Exercise | Candidates (deterministic rank) |
|---|---|
| Strait | 1 Surface + air + emergency reserves · 2 Surface reroute + air bridge · 3 Surface reroute |
| Kent | 1 Power + reserves + independent crossings · 2 Islanded + mobile power + priority-1 reserves · 3 Islanded critical utilities |
| London | 1 Relocate + second-source exports · 2 Relocate all services and programmes · 3 Relocate essential services |

Rank order: essential (priority-1) fulfilment, then overall fulfilment, then unmet + delayed cargo, then cost.

### Measured results (offline, deterministic)

| Exercise | Essential without → with top plan | All demand | Cargo | Resources |
|---|---|---|---|---|
| Strait closure | 40.0% → 100.0% | 40.0% → 90.5% | unmet 3,253 → 1,549 t; 23 t delayed | 1,055 t reserves, 33 aircraft sorties |
| Kent outage | 24.6% → 96.1% | 24.6% → 46.9% | 429 t on time via Newhaven–Dieppe and London–Paris air | 30 generators, 378 t reserves |
| London loss | 86.9% → 99.5% | 80.4% → 91.2% | unmet 1,502 → 1,030 t | 26 relocations (20 services, 6 programmes), 67.3 t/day spare |

## The recovery agent

One agent (`agents/resilience/agent.py`), restricted to the three exercises. It never queries the graph and never
computes figures. Its typed tools return Python-measured data:

| Tool | Returns |
|---|---|
| `inspect_exercise()` | Event, impact without recovery, key dependency paths, unavailable alternatives |
| `list_candidates()` | Prepared candidate ids, titles and summaries |
| `evaluate_plan(candidate_id)` | Measured metrics for one candidate |
| `compare_plans(candidate_ids?)` | Side-by-side measured metrics and the deterministic rank |
| `execute_plan(candidate_id, rationale)` | Builds and verifies the recovery branch; only for an evaluated candidate, once |

Bounds:
- At most **6 turns**, each a **single HTTP attempt** on the configured model (`FeatherlessLLM` bounded mode,
  500 tokens).
- There is no retry onto another model or provider; the model used is reported.
- On `LLMError`, a missing key, or a loop that ends without a valid execution, the top-ranked prepared plan is
  executed and labelled `fallback` with the reason.
- Provider message bodies are never logged.

Validated in the browser with the real model (Qwen2.5-72B-Instruct, 3 October 2026): all three exercises chose
the top-ranked candidate, in 5 bounded calls each.

## Branches

TuringDB has no change-on-change, so every branch is cut from main and replays its lineage:

- **Disruption branch**: `(:ResilienceBranch {role: 'disruption'})`. The Scenario is marked `active = true`,
  targets get `status = 'disabled' | 'destroyed'` and `ops_status = 'lost'`, and cascade hits are flagged
  `ops_status = 'at_risk'`.
- **Recovery branch**: `(:ResilienceBranch {role: 'recovery', parent: <disruption id>})`. The **same event is
  replayed first**, then the chosen options are set `active = true`. One `(:Allocation {option_id, kind, source,
  target, quantity, unit, ready_hours, until_hours})` is stored per generator, reserve, transfer and route.
  End-of-window states go in `resilience_state` (`restored | relocated | improved | residual`).

`spec` on the marker is base64url JSON with the event and the typed actions. After writing, each branch is read
back and the stored plan is re-simulated; the figures must equal the pre-execution measurement (`verified`).
`ResilienceLab.replay(branch)` rebuilds an identical branch from the spec alone. Main is never written. Branch
kinds `disruption` / `recovery` appear in the branch switcher and can be discarded.

## UI

- `ResiliencePanel.tsx`: the chat panel (suggestions submit fixed scenario ids).
- `ResilienceReport.tsx`: decision, plan comparison, before/after, simulation-time chart, action groups,
  resources, end states, limitations.
- `state/resilience.ts`: polls the job and hands the disruption cascade to `showCascade`.
- `map/resilienceLayers.ts`: the recovery overlay.

The cascade contract is extended additively: `CascadeResponse.origins` (several initial failures),
`origin_kind = "event"` and `measure = "service_loss"`.

Map styles:
- **Facility states**: red = disrupted/lost; blue ring = relocated service; green = restored; yellow = partly
  restored; orange = residual risk (larger means more service still missing).
- **Links**: white = recovery route (labelled with capacity, tonnes moved and readiness); blue = relocation;
  cyan = second-source export; yellow = generator allocation; violet = reserve release. Overlapping labels are
  decluttered by priority (routes first).

The report gives:
- essential and overall demand fulfilment, plus demands below their minimum;
- on-time, delayed and unmet cargo;
- services restored or relocated, and facilities still affected;
- stock, generator, fuel, aircraft, spare-output and programme-place consumption;
- each action group's capacity, readiness and measured benefit (leave one group out);
- recovery timing and residual limitations.

## Validation

```bash
.venv/bin/python -m pytest tests/agents/test_resilience.py -q                     # offline, ~5 s
DOVER_LIVE=1 .venv/bin/python -m pytest tests/agents/test_resilience_live.py -q   # live 6667, serial
```

The offline tests use deterministic provider doubles and cover:
- every exercise and its scenario rules;
- capacity conservation per day, ledger key and aircraft pool;
- stock, generator and spare conservation;
- stock depletion and the release-duration limit;
- cold-chain storage;
- unavailable alternatives and regional destruction;
- bounded steps, provider failure (fallback label), execute-before-evaluate refusal and plan-spec round trip;
- the runner end to end.

The live tests:
- show the live network equals the generator;
- run all three exercises with a scripted model against real branches (read back, verified, recovery replays the
  disruption);
- check that replay rebuilds an identical branch and that main's head is unchanged;
- check the routes mount only for `dover`;
- discard every branch they create.

## Known limits

- Daily demand granularity: a day's demand counts as met when its cargo arrives by the deadline, so readiness
  shows up in cargo timing more than in hour-by-hour service.
- Battery cover, road travel times, repair crews and the dormant `REPLENISHES` / `REPAIRS` links are not modelled.
- Reserve release lasts the option's 48 h at up to daily demand, so a two-day reserve never runs out inside these
  windows.
- Candidates are a prepared set of three per exercise; the agent chooses among them and cannot compose new plans.
