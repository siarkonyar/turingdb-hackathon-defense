# Agents - TuringDB branches as the search space

Three LLM agents treat **TuringDB changes (branches) as their search space**. Every candidate strategy,
countermeasure or disaster scenario is applied inside its own branch, evaluated from graph state, and kept
so branches can be compared with diffs. `main` is never modified. The agents run unattended: a supervisor
starts and heals the TuringDB server, so no operator has to shut anything down or intervene.

- **Threat** - finds the disruptions that cost the supply chain the most for the fewest attacks.
- **Defence** - analyses the worst threat branch and tests countermeasures that cut the projected loss.
- **Scenario** - answers a natural-language disaster question by simulating it in a branch and driving the map.

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

`agents/impact.py` computes one number from graph state on any ref: **projected supply-chain loss**.

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

Mounted only on the live backend (`OPSMAP_BACKEND=turingdb`):

| Endpoint | Purpose |
|---|---|
| `GET /agent/status` | Featherless availability + selected model |
| `POST /agent/scenario` `{question}` | run the scenario agent; returns branch, explanation, impact diff |
| `POST /agent/threat` | run the threat agent; returns the branches it explored |
| `POST /agent/defence` `{threat_branch}` | run the defence agent against a threat branch |
| `POST /agent/redblue` | the full threat -> defence pipeline with the comparison |

## Tests

```bash
uv run pytest tests/agents -q
```

- `test_guard.py`, `test_llm.py` - offline unit tests (no network).
- `test_branch_lab_live.py` - live branch mechanics against TuringDB (no LLM); skipped if the server is down.
- `test_agents_live.py` - end-to-end with **real Featherless calls and real branches**; skipped unless both
  the server and `FEATHERLESS_API_KEY` are available.
