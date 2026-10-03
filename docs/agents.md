# Agents - TuringDB branches as the search space

Three LLM agents treat **TuringDB changes (branches) as their search space**. Every candidate strategy,
countermeasure or disaster scenario is applied inside its own branch, evaluated from graph state, and kept
so branches can be compared with diffs. `main` is never modified. The agents run unattended: a supervisor
starts and heals the TuringDB server, so no operator has to shut anything down or intervene.

- **Threat** - finds the disruptions that cost the supply chain the most for the fewest attacks.
- **Defence** - analyses the worst threat branch and tests countermeasures that cut the projected loss.
- **Scenario** - answers a natural-language disaster question by simulating it in a branch and driving the map. It
  considers every layer, including the deep supply network (facilities, ports, the platforms they feed).

The model calls go to **Featherless AI** using the `FEATHERLESS_API_KEY` environment secret (never hardcoded,
never logged). The default model is `Qwen/Qwen2.5-72B-Instruct` with an automatic fallback down a preference
list when a model is gated for the account (`agents/config.py`); override with `FEATHERLESS_MODEL`.

```
Natural-language question / objective
          │
          ▼
   Agent reasoning (Featherless, JSON action protocol)
          │   schema / query / scout / places
          ▼
   Cypher queries (read-only, guarded)
          │
          ▼
   TuringDB branch  ← one per strategy / scenario (never main)
          │   strike / backup / reroute / restore / air-defence / wipe
          ▼
   Graph analysis  →  impact model (projected loss)  +  diffs
          │
          ▼
   Comparison + explanation  →  OpsMap map visualisation
```

## Run it

```bash
# 1. TuringDB (the agents also auto-start this if it is down)
uv run turingdb start -turing-dir "$(pwd)" -demon -in-memory -load theatre -start-timeout 20000

# 2. Autonomous red-vs-blue: threat explores, defence responds, branches compared by diff
uv run python -m agents.orchestrator --json result.json

# 3. A natural-language scenario question
uv run python -m agents.orchestrator --scenario \
  "A catastrophic event has destroyed everything across Manchester. How would this affect the rest of the city and its connected infrastructure?"
```

In the OpsMap UI (`OPSMAP_BACKEND=turingdb`), the agent branches appear in the branch switcher (Threat /
Defence / Scenario groups); switching to one re-colours the map from `GET /diff`. The **Scenario** button
(bottom bar) asks a question through `POST /agent/scenario` and flies the map to the simulated branch.

## The impact model (the objective)

The one-shot threat/defence agents use the original parts layer only. The turn-based match also scores
the deep network (see below). `agents/impact.py` computes one number from graph state on any ref: **projected supply-chain loss**.

- **Demand** (read from `main` once): every `(Site, Part)` pair that has purchase orders, weighted by PO
  count x part criticality (A=5, B=2, C=1).
- On the evaluated branch:
  - a **supplier works** iff it still exists, has >= 1 `POWERED_BY` feed and >= 1 `SOURCES_FROM` route;
  - a **part is available** iff >= 1 of its `SUPPLIED_BY` suppliers works (so backup suppliers count);
  - a **site works** iff it exists and has >= 1 `POWERED_BY` feed.
- `capability = weighted demand still satisfiable / total`, `projected loss = 1 - capability`.

Baseline loss on `main` is 0%. The whole thing is derived from TuringDB queries, so a branch's loss reflects
exactly the edits made in that branch.

## Branches are the search space (`agents/branches.py`)

`BranchLab` opens a change, applies one hypothesis inside it, evaluates the impact, and **keeps** the branch.
Each branch carries an `(:AgentBranch {role, label, parent, spec})` marker, so it is self-describing (the
OpsMap API reads it to label the branch) and **replayable**: if the in-memory server is restarted after a
runaway query, the lab rebuilds every branch from its spec. TuringDB cannot open a change on top of a
change, so a **defence branch is cut from `main` and replays the attack before adding its countermeasures** -
an independent, diff-comparable state (`main + attack + countermeasures`).

Comparison is by diff:
- **impact diff** - projected loss before/after, per site, critical parts (the headline number);
- **graph diff** - nodes added / removed / status-changed, reusing the OpsMap `/diff` machinery (drives the map).

## Actions (`agents/actions.py`)

| Agent | Actions |
|---|---|
| Threat | `strike_plant`, `strike_supplier`, `cut_route` |
| Defence | `add_backup_supplier`, `reroute_supplier`, `restore_power`, `prioritise_air_defence` |
| Scenario | `wipe_bbox` (+ `propagate` downstream impact) |

Attacks remove capacity; defences add redundancy; the scenario wipe destroys everything in a bounding box.
All of them change only the branch.

## Safety rails

- **Read guard** (`agents/guard.py`): agent-written Cypher must be a single linear-path read (the comma-join
  and other shapes that hung TuringDB 1.37 are rejected with a message the model can act on), every result is
  capped, and all writes are refused - writes only happen through the branch lab's typed actions.
- **Query watchdog** (`agents/runtime.py`): TuringDB has no documented query cancel, so each agent query runs under a
  deadline; a runaway triggers an automatic server restart and branch replay.
- **Scope**: the agents reason about graph dependencies and projected loss only. They do not produce
  operational attack instructions or identify real-world targets; the scenario agent analyses hypothetical
  disasters and their cascading effects on infrastructure.

## HTTP API

Mounted only on the live backend (`OPSMAP_BACKEND=turingdb`). Every agent action is a background job that
streams its progress over server-sent events; nothing blocks the HTTP server. Full contract: `docs/api.md`.

| Endpoint | Purpose |
|---|---|
| `GET /agent/status` | Featherless availability + selected model |
| `POST /agent/scenario` `{question}` | scenario agent job -> `{job_id}`; stream `/agent/jobs/{id}/events` |
| `POST /agent/threat`, `/agent/defence`, `/agent/redblue` | the one-shot agents, same job pattern |
| `POST /match` `{base_branch, rounds}` | turn-based red-vs-blue wargame -> `{match_id}`; stream `/match/{id}/events` |
| `POST /match/{id}/inject` `{text}` | operator event, applied before the next round |
| `POST /match/replay` `{file}` · `GET /matches` | replay a saved match with no LLM calls |

## The wargame (`agents/match.py`)

Each round red plays ONE disruption and blue ONE countermeasure, each a branch stacked on the current head
(a fresh change from main that replays the head's lineage, because TuringDB 3.0 cannot stack changes). A move is
one decision: the options are in the prompt, so it is usually a single LLM call, with at most 3 calls
(a format retry or one read query) and a flagged fallback. Loss is measured against the base branch.
Injects run the scenario agent on the head. Matches are saved to `matches/<id>.json` and replayable
without the LLM (`uv run python -m agents.match --replay demo`).

### Deep-network capability (`deep_impact.py`, `deep_actions.py`, `match_deep.py`)

The match score is **75% deep capability loss + 25% original parts loss** (`DEEP_WEIGHT = 0.75`). Each
move records both absolute component losses as `breakdown.deep_pct` and `breakdown.legacy_pct`; the feed
shows the split. If the graph has no deep layer, the score uses the original layer alone. Loss versus a
scenario base is the difference between the combined scores, in percentage points.

The deep model loads the bill of materials, facilities, export routes and country production shares from
main, reads each branch's edited state, then evaluates it in Python:

- Facility output is zero when removed, closed, or deprived of all its original power feeds. Otherwise it
  uses its best export route. A closed/removed port retains `OVERLAND_FLOOR = 0.4` for overland/air fallback.
  A blocked chokepoint reduces route output by `REROUTE_LOSS = 0.35` times its share of that port's shipments
  (summed blocked shares are capped at 1). An alternative port runs at `ALT_PORT_EFFICIENCY = 0.8`.
- Item production is the share-weighted output of its makers. Deleted makers retain their original share
  in the denominator, so losing a facility cannot improve the surviving makers' output. Export controls zero the controlling country's
  makers for that item and reduce its mineral/material `PRODUCTION_SHARE`. Item availability is the minimum
  of production and each buffered input availability: `1 - (1 - child_availability) * (1 - TIER_BUFFER)`.
  `TIER_BUFFER = 0.3` absorbs 30% of an input shortfall at each tier. Stockpiled components/materials/minerals
  have availability at least `STOCKPILE_FLOOR = 0.8`.
- Platform weights mix equal programme share and annual value share (`demand * unit_cost`), with
  `EQUAL_SHARE = 0.5`. Deep loss is one minus weighted platform availability.

**These constants are gameplay assumptions, not calibrated estimates of real production.** Seven buffered
input tiers make mineral export controls relatively weak, so they need not be selected in every match.
The one-shot threat/defence agents retain their original impact model and action set.

| Side | Deep moves |
|---|---|
| Red | `close_port`, `block_chokepoint`, `export_controls` (outside NATO/EU), `facility_outage` |
| Blue | `reroute_exports`, `replace_facility`, `second_source`, `stockpile`, `harden` |

Candidate effects are previewed in Python on the current head before the model chooses. Prompts keep
two ranked options per action kind and complete JSON so lower-ranked production disruptions remain visible;
red is encouraged to explore at least three useful disruption kinds across a multi-round exercise. Rerouting spreads
exporters across up to three alternative ports; replacement qualifies makers for everything the affected
facility produced; second sources prefer allied countries and add a production share of 50. Hardening
prevents subsequent closures/outages on the asset. Red cannot repeat its previous action kind on its next
turn. Invalid model decisions retry, then use a ranked fallback and alternates if that fallback is refused.
All edits use the branch action dispatcher and replay with the lineage; main remains untouched.

Deep move map effects flash/pulse the port, chokepoint or facility and draw arcs to affected exporters and
final-assembly facilities of platforms whose availability changed. These effects come from the capability
model, since a closure flag is not a node deletion in the ordinary OpsMap diff.

```bash
OPSMAP_BACKEND=turingdb uv run python -m agents.match --base main --rounds 4 --save-as demo
uv run python -m agents.match --replay demo --speed 4
```

### Demo runbook (all in the browser)

1. `.env` with `OPSMAP_BACKEND=turingdb` and `FEATHERLESS_API_KEY` (see `.env.example`), TuringDB 3.0 running
   in-memory with `theatre`, then `uv run uvicorn api.main:app` and `npm --prefix ui run dev`.
2. **Scenario** → "everything in Manchester is destroyed" → Simulate (branch, 13.8% loss).
3. **Wargame** → base = main for the deep-network demo, or that scenario branch; choose 4 rounds → Start. Type "the Liverpool port is closed" → Inject during
   round 1; it lands before round 2 as an amber card and a new head.
4. LLM down? The chip says so and **Replay saved match** plays `matches/demo.json` (a real recorded match)
   with its original timing and no model calls, rebuilding every branch on TuringDB.

Measured locally (Qwen2.5-72B, TuringDB 3.0): warm moves usually take 3-8 s of LLM time and 1-3 s of
TuringDB time. A cold start or model retry can take longer.

## Tests

```bash
uv run pytest tests/agents -q
```

- `test_guard.py`, `test_llm.py` - offline unit tests (no network).
- `test_branch_lab_live.py` - live branch mechanics against TuringDB (no LLM); skipped if the server is down.
- `test_deep_impact.py`, `test_match.py` - offline capability rules, no-repeat and fallback behavior.
- `test_match_live.py` - deep actions, capability recovery, map effects and replay against live TuringDB
  with a fake model.
- `test_agents_live.py` - end-to-end with **real Featherless calls and real branches**; skipped unless both
  the server and `FEATHERLESS_API_KEY` are available.

### Validation on 3 October 2026

- Full Python suite: 197 passed, including all four real Featherless agent tests and live TuringDB tests.
- After preserving deleted-maker shares, focused deep model / match / live match tests: 39 passed.
- UI: typecheck, 27 tests and production build passed.
- Four-round real Qwen2.5-72B match: eight moves, no fallbacks, final combined loss 22.5% (deep 30.0%,
  original parts 0.0%). Red used ports, a facility outage and a chokepoint; blue rerouted exports, qualified
  replacement production and hardened a port. Export controls were offered but not selected.
- `matches/demo.json` records that match. Browser replay completed with ports/facilities/chokepoint effects
  and split scores. Map stacking and feed sizing were fixed so effects stay behind controls and long names fit.
- Invalid model choices retry in the CLI as well as the API: `MoveRejected` lives in `match_errors.py` to
  avoid separate exception identities when `agents.match` runs as `__main__`.


### Optional Featherless Simple Jev Blue

Set `BLUE_JEV_ENABLED=1` in the server environment or `.env` to opt in for standalone defence
and classic/strategic wargames. Red keeps its original decision flow. See [Jev integration](jev.md)
for the verified API contract, configuration, bounds, telemetry and validation limitations.
