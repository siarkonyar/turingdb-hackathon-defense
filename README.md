<img src="assets/banner.png" alt="TuringDB × EDTH - Datasets, example use cases and setup guide for TuringDB" width="100%">

# TuringDB × EDTH Hackathon - Ready-to-Use Datasets & Use Cases

A ready-to-run pack of **graph datasets for the EDTH hackathon**, built on
[**TuringDB**](https://turing.bio). Clone this repo, point a TuringDB server at it, and you
have seven domain graphs - supply chain, a deep multi-tier defense supply chain, logistics risk, drone-swarm telemetry, global power
infrastructure, POLE crime investigation, and a cyber attack-scenario knowledge base -
loadable and queryable in seconds, plus a browser visualizer.

No data wrangling required: the graphs are **pre-built** and committed under [`graphs/`](graphs/).
Per-dataset documentation (schema, example queries, licensing) lives in [`docs/`](docs/).

> [!IMPORTANT]
> **These are just example datasets - you are not required to build on them.** They exist to
> get you querying in seconds, not to constrain your project. **Bring your own data**: take any
> **CSV or JSONL** file, turn it into a TuringDB graph with a short import script, and build on
> that instead. Mix the provided graphs with your own, or ignore these entirely - whatever fits
> your hack. See the [`turingdb` Claude Code skills](#claude-code-skills) (or the
> [Python SDK docs](https://docs.turingdb.ai/pythonsdk/reference)) for how to load your own
> CSV/JSONL into a graph.

---

## What is TuringDB?

TuringDB is a **high-performance, in-memory, column-oriented graph database engine** designed
for analytical and read-intensive workloads. Built from scratch in C++, it delivers
**millisecond query latency on graphs with millions of nodes and edges** - commonly **~200×
faster than Neo4j** on deep multi-hop queries.

### Key features

- **[Performance-first architecture](https://docs.turingdb.ai/concepts/columnar_storage)** -
  in-memory, column-oriented storage with streaming query processing; 0.1–50 ms latency on
  10M+ node graphs, [~200× faster than Neo4j](https://docs.turingdb.ai/benchmarks/results-summary)
  on deep multi-hop queries.
- **[Zero-lock concurrency](https://docs.turingdb.ai/concepts/zero_locking)** - reads and writes
  never compete; every transaction runs on its own immutable
  [snapshot](https://docs.turingdb.ai/concepts/snapshots) (snapshot isolation).
- **[Git-like versioning](https://docs.turingdb.ai/concepts/versioning_system)** - commit graph
  versions, branch, merge, and time-travel through history for reproducibility and auditability.
- **Developer friendly** - [OpenCypher](https://docs.turingdb.ai/query/cypher_subset) query
  language and a [Python SDK](https://docs.turingdb.ai/pythonsdk/reference) whose `query()`
  returns a pandas DataFrame, plus an HTTP server (`:6666`) and browser visualizer (`:8080`).

Each graph is a self-contained, versioned store (commits, dataparts) under `graphs/<name>/` -
which is exactly what this repo ships.

---

## Dataset catalog

| Graph | Domain | Nodes | Edges | Docs |
|---|---|--:|--:|---|
| `supply_chain` | Aerospace / defense supply chain (parts, suppliers, POs, quality incidents) | 30,380 | 90,402 | [docs/supply_chain.md](docs/supply_chain.md) |
| `supply_chain_deep` | **Deep** multi-tier defense supply chain (platform → BOM → minerals, supplier network, ownership chains, sea lanes & chokepoints, shipments, real disruptions) - 5-12 hop queries | 132,834 | 763,831 | [docs/supply_chain_deep.md](docs/supply_chain_deep.md) |
| `logistics_risk` | Supply-chain **risk** & performance indicators (shipments, suppliers, countries, risk class) | 117,718 | 233,242 | [docs/logistics_risk.md](docs/logistics_risk.md) |
| `drone_swarm` | Drone-swarm coordination telemetry (positions, battery, formation, mission, trajectories) | 21,028 | 99,980 | [docs/drone_swarm.md](docs/drone_swarm.md) |
| `power_plants` | Global power infrastructure (plants, fuels, owners, countries, plants within 10 km) | 45,262 | 149,218 | [docs/power_plants.md](docs/power_plants.md) |
| `poledb` | POLE crime investigation (people, associates, crimes, officers, vehicles, phone calls, locations) | 61,521 | 105,840 | [docs/poledb.md](docs/poledb.md) |
| `attack_scenarios` | Cyber attack knowledge base (scenarios → MITRE ATT&CK techniques, tools, categories) | 18,354 | 60,014 | [docs/attack_scenarios.md](docs/attack_scenarios.md) |
| `theatre` | All seven fused into one operating picture (incl. `supply_chain_deep`), with synthetic sites, bridges and intel `Report` nodes. Generated: `uv run python fusion/build_theatre.py` | 426,969 | 1,621,798 | [docs/theatre.md](docs/theatre.md) |

The isolated **London–Dover–Paris demo** is generated independently of those graphs:
`.venv/bin/python scripts/run_dover_demo.py` (map on port 5174). It has 6,095 synthetic nodes,
23,914 edges and 12-degree supply cascades. Schema, assumptions, scenarios and the future-agent
contract are in [docs/dover.md](docs/dover.md). No worldwide data is imported into `dover`.

---

## Example use cases

These graphs are picked for **defense, resilience, and intelligence** scenarios:

- **Supply-chain resilience** (`supply_chain`, `logistics_risk`) - trace a delayed purchase
  order or a quality defect back through the part to every affected site; find where high-risk
  shipments concentrate by supplier, product, and country; quantify supplier reliability
  (on-time-in-full) and single-source risk.
- **Deep, multi-tier dependency analysis** (`supply_chain_deep`) - follow a platform through 8
  levels of bill of materials to the mines and countries behind it; trace mine-to-prime supplier
  chains; unmask foreign or sanctioned ultimate owners behind holding companies; measure the
  impact of Red Sea reroutes, chokepoint closures and export controls on shipments.
- **Critical-infrastructure mapping** (`power_plants`) - map generation capacity by country
  and fuel; identify ownership concentration and fuel-dependency for energy-security analysis;
  use `NEAR` edges (plants within 10 km) to find co-located clusters and cross-border neighbours
  exposed to a single strike or natural hazard.
- **Autonomous-systems / ISR** (`drone_swarm`) - reconstruct each drone's trajectory over
  time, correlate collision warnings with formation and mission, and snapshot the full swarm
  state at any instant.
- **Criminal-network / investigation analysis** (`poledb`) - map associates through `KNOWS`
  and family links, trace crimes to their location, investigating officer, suspects and
  vehicles, and reconstruct phone-call patterns across a person's contacts.
- **Attack knowledge base & ATT&CK mapping** (`attack_scenarios`) - pull full attack playbooks
  (steps, impact, detection, remediation), pivot from a MITRE ATT&CK technique to every attack
  that uses it, and rank the tools attackers rely on most.

Each dataset's doc lists concrete starter queries.

---

## Prerequisites

The only thing you need is a Python package manager - we recommend [`uv`](https://docs.astral.sh/uv/).
Installing the `turingdb` package gives you **both** the `turingdb` CLI (on your `PATH`) and the
Python SDK (as a library) - there's nothing else to install separately.

This repo is already a `uv` project pinned to `turingdb==3.0` (see [`pyproject.toml`](pyproject.toml)),
so `uv sync` (or any `uv run ...`) installs everything. For a project of your own:

```bash
uv init my-project
uv add "turingdb==3.0"
```

(Or with pip: `pip install "turingdb==3.0"`.)

---

## Quick start

### 1. Start the server pointed at this repo

The repo root **is** a TuringDB "turing-dir" (it contains a `graphs/` store) and a `uv` project.
Clone it, install the pinned dependencies, and start the server with the visualizer enabled:

```bash
git clone https://github.com/turing-db/turingdb-hackathon-defense.git
cd turingdb-hackathon-defense
rm -rf .git                 # so you can start your own git repo in the cloned directory

uv sync                     # installs turingdb==3.0 (CLI + SDK) into .venv
uv run turingdb start -turing-dir "$(pwd)" -ui   # look for graphs in the current dir, start the visualizer UI
```

- **`:6666`** - database (HTTP API used by the SDK)
- **`:8080`** - open <http://localhost:8080> for the interactive visualizer

> The server recreates its runtime dirs (`data/`, `logs/`, lock/socket) on first start - those
> are git-ignored. Only the `graphs/` store is versioned here.

### 2. Query from Python

```python
from turingdb import TuringDB

c = TuringDB("json", host="http://localhost:6666")

# pick a graph (see the catalog below)
c.load_graph("power_plants")
c.set_graph("power_plants")

# results come back as a pandas DataFrame
df = c.query("""
  MATCH (p:PowerPlant)-[:LOCATED_IN]->(co:Country {country_code:'USA'}),
        (p)-[:PRIMARY_FUEL]->(f:Fuel)
  RETURN p.name, f.name AS fuel, p.capacity_mw
  LIMIT 20
""")
print(df)
```

### 3. Explore in the visualizer

Open <http://localhost:8080>, choose a graph, and run the default
`MATCH (n) RETURN n LIMIT 100` to see a slice - then click nodes to expand neighbours.

---

## Claude Code skills

This repo bundles the [**TuringDB Claude Code skills**](https://github.com/turing-db/turingdb-skills)
under [`skills/turingdb/`](skills/turingdb) - they teach Claude Code how to start, query, write,
and manage TuringDB graphs (including the Cypher dialect's quirks), so you can drive these
datasets in plain English instead of memorizing the SDK.

Install with the skills CLI:

```bash
npx skills add https://github.com/turing-db/turingdb-skills
```

…or copy the bundled folder straight into your Claude Code skills directory:

```bash
cp -r skills/turingdb ~/.claude/skills/
```

Then start a Claude Code session and type `/turingdb` followed by what you want to do, e.g.:

- `/turingdb start the server at the current directory and load power_plants`
- `/turingdb query the highest-capacity plants in the USA with their fuel`
- `/turingdb find which suppliers have the most quality incidents in supply_chain`

| File | Covers |
|------|--------|
| `SKILL.md` | Entry point - routes to the right reference for your task |
| `startup.md` | Install the package, connect to a server (or run embedded), load/create a graph |
| `querying.md` | `MATCH`, `WHERE`, joins, ordering, functions |
| `writing.md` | `CREATE`, `SET`, and the change/commit workflow |
| `importing.md` | Import external data - JSONL, GML, Parquet, Neo4j migration |
| `algorithms.md` | Shortest path (Dijkstra), vector/embedding search |
| `introspection.md` | Explore schema, versioning, time travel, SDK reference |

### 4. OpsMap - the operating picture

`ui/` + `api/` put the `theatre` graph on a map: strike simulation with cascade arcs, branch
diff and competing intel hypotheses, with TuringDB query latency on screen.

```bash
uv run python fusion/build_theatre.py && uv run turingdb stop -turing-dir "$(pwd)"   # once (~2 min)
uv run turingdb start -turing-dir "$(pwd)" -demon -in-memory -load theatre -start-timeout 60000
OPSMAP_BACKEND=turingdb uv run python -m api.seed_hypotheses
OPSMAP_BACKEND=turingdb uv run uvicorn api.main:app --port 8000
npm --prefix ui install && npm --prefix ui run dev     # http://localhost:5173
```

Drop `OPSMAP_BACKEND=turingdb` to run on the bundled mock fixtures without a server. See
[ui/README.md](ui/README.md) and the API contract in [docs/api.md](docs/api.md).

![OpsMap strike simulation](docs/opsmap-strike.png)

### 5. Agents - TuringDB branches as the search space

Three LLM agents (powered by [Featherless AI](https://featherless.ai)) use TuringDB **branches as their
search space**: every strategy or scenario is explored in its own change, evaluated from graph state, and
kept for comparison by diff - `main` is never touched. They run unattended; a supervisor starts and heals
the server, so nothing has to be shut down by hand.

- **Threat** - finds the disruptions that cause the most supply-chain loss for the fewest attacks.
- **Defence** - tests countermeasures (backup supplier, alternative route, power feed, air-defence) against
  the worst threat branch and proves the loss reduction with a diff.
- **Scenario** - answers a natural-language disaster question ("a catastrophic event has destroyed everything
  across Manchester...") by generating Cypher, simulating it in a branch, and driving the map.

```bash
export FEATHERLESS_API_KEY=...        # already set as an environment secret here
uv run python -m agents.orchestrator                       # threat -> defence, with the comparison
uv run python -m agents.orchestrator --scenario "A catastrophic event has destroyed everything across Manchester..."
```

In the OpsMap UI (live backend) the agent branches appear in the branch switcher and the **Scenario** button
runs the scenario agent and visualises the result on the map. Full write-up: [docs/agents.md](docs/agents.md).

---

## Repo layout

```
turingdb-hackathon-defense/  ← repo root (point -turing-dir here)
├── README.md               ← you are here
├── graphs/                 ← prebuilt, versioned TuringDB graph store
│   ├── default/         ← empty default graph (needed for a clean server start)
│   ├── supply_chain/
│   ├── logistics_risk/
│   ├── drone_swarm/
│   ├── power_plants/
│   ├── poledb/
│   ├── attack_scenarios/
│   └── theatre/         ← all six fused (built by fusion/)
├── fusion/              ← builds `theatre`, its queries and versioning demo
├── agents/              ← threat / defence / scenario LLM agents (Featherless + TuringDB branches)
├── api/                 ← OpsMap FastAPI backend (TuringDB or mock fixtures; mounts /agent/*)
├── ui/                  ← OpsMap map UI (Vite + React + MapLibre + deck.gl)
├── docs/                ← per-dataset schema, queries, licensing; api.md (OpsMap API)
│   ├── supply_chain.md
│   ├── logistics_risk.md
│   ├── drone_swarm.md
│   ├── power_plants.md
│   ├── poledb.md
│   ├── attack_scenarios.md
│   └── theatre.md
└── skills/              ← TuringDB Claude Code skills (/turingdb)
    └── turingdb/
```

---

## Licensing

Each dataset retains its **original source license** - see the "License" section in each
doc. Summary:

| Graph | Source license |
|---|---|
| `supply_chain` | MIT (synthetic data) |
| `supply_chain_deep` | MIT (synthetic data; generator in [`scripts/`](scripts/)) |
| `logistics_risk` | Apache-2.0 |
| `drone_swarm` | CC BY 4.0 |
| `power_plants` | CC BY 4.0 (WRI Global Power Plant Database) |
| `poledb` | OGL v3.0 (UK open police data; synthetic personal entities) |
| `attack_scenarios` | MIT |

When redistributing, retain the relevant attribution/notice and indicate that the data was
converted into a TuringDB graph.
