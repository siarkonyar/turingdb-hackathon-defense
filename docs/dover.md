# London–Dover–Paris resilience dataset

This is the handoff for building a **new scenario agent** over the isolated `dover` graph. It contains data, event definitions and possible recovery actions. It does not implement an agent, apply the events, allocate recovery resources, or calculate time-dependent service loss.

**Implemented for three exercises:** `scenario:strait_closure`, `scenario:kent_power` and `scenario:london_loss` now have a deterministic disruption/recovery engine, one bounded recovery agent, disruption and recovery branches, and a map-side chat panel. See `docs/dover-resilience.md`. The other six Scenario definitions remain data only.

All facility positions, organisations, units, demands, capacities, durations, stocks and costs are **fictional exercise assumptions**. Town names are geographic anchors. Facilities are placed with deterministic jitter around town centroids; they are not actual hospitals, military installations, power stations or airports. The NATO support units are entirely fictional. The dataset supports disruption and continuity exercises; it contains no targeting or weapon-effect model.

## Isolation and running the demo

The generator never reads the seven bundled graphs or `theatre`. There are no shared nodes, imported IDs, joins or external edges. Every node and edge has `source = 'dover_synthetic_v1'` and `synthetic = true`. The demo uses a separate database root and port, and does not change the existing `.env` or original graphs.

```bash
# Generate JSONL and the complete schema/count/hash manifest, without a server.
.venv/bin/python -m datasets.dover.build

# Import and verify the graph on its dedicated local database server.
.venv/bin/python -m datasets.dover.build --load

# Run the database in memory, the API, and the focused map together.
.venv/bin/python scripts/run_dover_demo.py
```

The launcher uses:

| Component | Value |
|---|---|
| Graph | `dover` |
| Database | `http://localhost:6667` |
| Database root | `data/dover-runtime/` |
| Map | `http://127.0.0.1:5174` |
| API | `http://127.0.0.1:8001` |
| UI profile | `VITE_OPSMAP_PROFILE=dover` |
| Generated JSONL | `data/dover-runtime/data/dover.jsonl` |
| Generated manifest | `data/dover-runtime/manifest.json` |
| Generated store | `data/dover-runtime/graphs/dover/` |

The map starts centred on Dover Strait at longitude 1.52, latitude 51.02. Its focused UI has four layer controls (plants, facilities, ports and chokepoints), affected-facility/cascade-degree indicators, and a compact branch/Impact/Diff footer. The historical timeline, empty worldwide layers and manual strike controls are removed from the demo. The original map profile remains available through the existing commands. The isolated graph exposes the existing node browser, neighbours, branch/diff functionality and read-only Impact cascade. The original theatre agent and wargame routes are disabled for `dover`, because their impact model and action contracts assume a different dataset.

The launcher stops and restarts **its own Dover server** before starting the map, which discards any ephemeral Dover branches from a previous run. It never stops the server on port 6666. Ctrl-C stops the processes owned by the launcher. Run the launcher once per demo session. Existing graph data with a different build fingerprint is refused rather than overwritten; retain or archive the dedicated runtime and build into a fresh runtime after changing the generator.

Generated stores and exports are under the already ignored `data/` directory. The source files, documentation and tests are the reproducible dataset definition. No original graph needs to be deleted to keep the demo isolated.

## Geography and scope

There are 26 populated towns within longitude -0.6 to 3.15 and latitude 48.7 to 51.7. The western Channel detour remains inside this corridor.

| Region | Towns |
|---|---|
| London | London, Croydon |
| Kent | Dartford, Gravesend, Medway, Maidstone, Sittingbourne, Canterbury, Ashford, Folkestone, Dover, Deal |
| Sussex | Newhaven |
| Coastal France | Calais, Dunkirk, Boulogne |
| Northern France | Saint-Omer, Arras, Amiens, Abbeville |
| Normandy | Dieppe, Rouen |
| Paris Corridor | Beauvais, Creil |
| Paris | Paris, Saint-Denis |

Each town has a grid supply, substation, water works, telecom exchange, fuel depot, emergency depot, repair-team pool, general emergency reserve, road hub, rail hub and customs hub. It also has ten local producers, ten distribution facilities, ten sector services and three shared service programmes.

## Scale

| Label | Count | Meaning |
|---|---:|---|
| Facility | 1,252 | Utilities, terminals, production stages, distribution and beneficiary services |
| RecoveryOption | 4,064 | Dormant, constrained continuity or recovery possibilities |
| Stockpile | 286 | 26 general reserves and 260 product-specific reserves |
| Demand | 260 | One daily product requirement per town and sector |
| Platform | 78 | Service capabilities, not weapon platforms |
| ResourcePool | 30 | 26 repair-team pools and four cargo-aircraft pools |
| PowerPlant | 26 | Fictional town grid-supply nodes |
| Place | 26 | Town anchors |
| Consignment | 20 | Ten recurring supply flows in each direction |
| Company | 11 | Fictional sector cooperatives |
| Component | 10 | Broad product classes |
| Scenario | 9 | Dormant example event definitions |
| Region | 8 | Geographic event-selection groups |
| Route | 6 | Bidirectional cross-border transport corridors |
| Port | 5 | Dover, Calais, Dunkirk, Newhaven, Dieppe freight terminals |
| Country | 2 | United Kingdom and France, scoped to the corridor |
| Chokepoint | 1 | Dover Strait maritime-access node |
| Dataset | 1 | Version, seed, bounds and build fingerprint |

Total: **6,095 nodes and 23,914 edges**. The manifest records the exact label counts, relationship counts, property inventories and JSONL SHA-256. Seed: **20261003**. Node IDs are contiguous in the export; stable `entity_id` values are the application identifiers.

## Products, demands and daily flow

Each town requires the following products. Tonnes are an illustrative common transport unit; medical supplies and repair modules are not calibrated in real-world clinical or engineering units.

| Sector key | Product | Tonnes/day/town | Deadline, hours | Cold chain |
|---|---|---:|---:|---|
| `medical` | Medical consumables | 2 | 24 | Yes |
| `food` | Food packs | 12 | 48 | No |
| `water` | Water treatment supplies | 8 | 24 | No |
| `fuel` | Packaged generator fuel | 20 | 36 | No |
| `repair` | Vehicle repair kits | 6 | 72 | No |
| `power` | Electrical repair modules | 5 | 24 | No |
| `comms` | Communications spares | 1.5 | 12 | No |
| `shelter` | Emergency shelter packs | 10 | 48 | No |
| `cold` | Temperature-controlled medicines | 1 | 12 | Yes |
| `sanitation` | Sanitation consumables | 4 | 36 | No |

The baseline supplies **60% from the opposite country and 40% from local production**. Every consignment carries the imported daily share for all 13 receiving towns. Imported volume is **542.1 tonnes/day in each direction**, or **1,084.2 tonnes/day combined**, below the primary route's shared 1,600-tonne capacity. `FULFILLS.allocation_tonnes` assigns the daily imported share to each town's Demand; its allocations sum to the consignment's tonnes.

Medical, cold-chain medicine and water demands have priority 1; other demands have priority 2. Every Demand sets a minimum service fraction of 0.8. Repair and shelter demands permit backlog. Cold-chain stock has a 72-hour illustrative shelf life; other product shelf life is 720 hours. Product-specific emergency reserves hold two days of demand but have a separate 72-hour reserve expiry assumption.

## Long dependency chains and convergence

There are ten chains in each direction. UK origin towns are London, Maidstone and Medway, selected cyclically by sector. French origin towns are Paris, Rouen and Amiens. After crossing, the chains pass through Calais and Amiens for UK-to-France flows, and Dover and Ashford for France-to-UK flows.

```text
Exporting inputs
  -> import customs (requires the crossing)
  -> inbound sorting
  -> processing
  -> manufacturing
  -> quality release
  -> packing
  -> regional staging
  -> freight dispatch
  -> town distribution (also receives 40% local supply)
  -> sector service
  -> shared support programme
  -> service capability
```

The staging activities are synthetic processing/handling stages for the broad product classes. They are not a detailed bill of materials or clinical workflow. Multiple sectors converge on each town's programmes:

| Programme facility | Required sector services |
|---|---|
| Fictional NATO support unit | Medical, food, fuel, repair, communications |
| Fictional military hospital | Medical, cold-chain medicine, water, electrical repair, sanitation |
| Civil emergency centre | Shelter, food, water, communications, fuel |

Each programme depends on electricity as well. Its Platform capability depends on that programme facility. A hospital can therefore lose capability because it has no power, consumables, cold storage, water or sanitation, even if its building survives.

Utilities and transport create shared failure points: a grid outage affects a substation; the substation affects water, communications and fuel handling; communications also affect road/customs/air terminals and production stages. Fuel, power-repair and communications services have delayed `REPLENISHES` or `REPAIRS` links back to infrastructure. Those links are dormant to avoid pretending that infrastructure repair occurs instantaneously.

The active `DEPENDS_ON` graph is a directed acyclic graph. Delayed restoration links and dormant alternatives are deliberately outside it.

## Transport alternatives

| Route ID suffix | Mode | Shared tonnes/day | Transit hours | Requires Dover Strait |
|---|---|---:|---:|---|
| `dover_calais` | Sea | 1,600 | 8 | Yes |
| `dover_dunkirk` | Sea | 500 | 10 | Yes |
| `western_channel` | Sea, Newhaven–Dieppe | 240 | 18 | No |
| `tunnel` | Rail, Folkestone–Calais | 320 | 6 | No |
| `london_paris_air` | Air | 64 | 4 | No |
| `kent_beauvais_air` | Air, Ashford–Beauvais | 64 | 5 | No |

All routes are bidirectional and their capacities are shared across both directions, sectors and recovery actions. Each requires both terminals and last-mile road hubs. Airports also require electricity, communications and aviation fuel. Each air route requires its terminal aircraft pools. The four pools each contain four illustrative 16-tonne-payload aircraft with one rotation/day; the route ceiling remains 64 tonnes/day, not 128 by adding both endpoint pools.

All twenty consignments initially use Dover–Calais. The tunnel, western Channel and both air routes are listed through dormant `CAN_USE` edges. Dover–Dunkirk is present as another sea corridor; it shares the strait and is not a solution to maritime strait closure.

A **Dover Strait maritime closure does not close the tunnel or the entire English Channel**. A Kent power outage can independently disable the tunnel, Ashford cargo terminal and Dover operations. The combined event therefore removes some otherwise useful alternatives. London infrastructure loss independently removes the London cargo terminal and aircraft pool.

The four independent routes have a combined nominal ceiling of 688 tonnes/day, below 1,084.2 tonnes/day of baseline imports. This arithmetic is an upper bound before outages, activation, loading, last-mile capacity or deadlines. Air cargo alone cannot replace all freight. Splitting consignments is explicitly allowed, enabling prioritisation and mixed-mode transport. It must still respect capacities, compatibility, remaining stocks and arrival times.

## Recovery options and their limits

`HAS_RECOVERY` links an affected asset to a RecoveryOption. `REQUIRES` links that option to actual provider, pool, stock, crew or route nodes. Every Facility, Port, PowerPlant and the Chokepoint has at least one recovery option. This guarantees a **candidate to evaluate**, not that every option remains feasible under every combined event.

| Kind | Data meaning |
|---|---|
| `mobile_power` | Allocate one shared mobile generator and local fuel; activate after 2 hours; 2 MW; illustrative 72-hour duration |
| `islanded_generation` | Same finite generator/fuel pools for grid-service continuity; activate after 4 hours |
| `repair` | One shared repair team and general reserve; activate after 24 hours; does not reconstruct destroyed facilities |
| `second_source` | Obtain replacement output from a same-country provider in a different region, with a road hub; 12-hour activation and 20 tonnes/day spare-output ceiling |
| `relocate_service` | Continue service at a different-region hospital or programme facility; 12-hour activation and 100-person illustrative spare service capacity |
| `release_stock` | Product-specific reserve; 1-hour activation; up to daily demand for 48 hours; consumes the shared stored quantity |
| `alternate_port` | Evaluate the western maritime corridor and a different port; 8-hour activation; terminal and route restrictions still apply |
| `reroute_*` | Evaluate a named independent route; activation after 4 hours for air or 8 hours for rail/sea |

General emergency reserves have 120 tonnes, three mobile generators, two mobile water units, 72 hours of generator fuel and eight hours of battery cover. Repair pools have four teams and 32 daily work-hours. A general stock node represents these distinct inventory fields; its 120 tonnes is not freely convertible to every product. Product-specific reserves are separate.

All option capacities must be constrained by their providers and pools. Two actions drawing on the same producer do not each get a fresh 20 tonnes/day. Three generators cannot support hundreds of facilities simultaneously, and the same generator cannot be assigned both through a grid option and through a facility option. Read `power_demand_mw`, `provided_mw`, fuel consumption and remaining duration. Local producers declare `spare_tonnes_day = 20`; beneficiary facilities declare `spare_service_people = 100`. Never treat repeated values on option nodes as independent inventory.

Second-source and relocation providers are selected deterministically outside the target's region. For specialised terminals, the general emergency depot candidate is a mobilisation resource, not a certified replacement airport/tunnel. Certification, a usable receiving site and transport feasibility still need to be established. Local source candidates can share broader-country or crossing dependencies. The presence of an alternative is not proof of independence from all simultaneous disruptions.

All options are initially inactive. No option grants immunity. `restores_destroyed_asset = false` means service continuity or degraded-site recovery cannot bring back a physically destroyed asset. An option can fail because its stock location, crew, fuel handling, airport, road connection or provider is also unavailable.

## Example event definitions

These are seeds for exercises, not a hard-coded list of questions. Any entity, place or region can be selected to define other events.

| Scenario entity ID | Directly disabled assets | Duration, hours |
|---|---|---:|
| `scenario:strait_closure` | Dover maritime-access node | 72 |
| `scenario:kent_power` | All ten Kent grid supplies | 48 |
| `scenario:london_loss` | London/Croydon facilities, grid supplies, stockpiles and resource pools | 168 |
| `scenario:calais_port` | Calais freight port | 36 |
| `scenario:tunnel_loss` | Folkestone tunnel terminal | 24 |
| `scenario:paris_power` | Paris and Saint-Denis grid supplies | 48 |
| `scenario:fuel_shortage` | All Kent fuel depots | 72 |
| `scenario:comms_loss` | Dover and Calais communications exchanges | 12 |
| `scenario:combined` | Dover maritime access plus all Kent grid supplies | 72 |

Every Scenario is `active = false`, with `start_hours = 0` and `DISABLES.initial_loss_fraction = 1`. These edges define only the initial disruption. Downstream loss must be derived from active dependencies and time. Regional catastrophic loss includes stocks and aircraft/crew pools so that a destroyed London depot cannot magically supply a London recovery action. Place/Region/Demand/Scenario/RecoveryOption metadata remain available for explanation.

For `regional_loss`, disabled assets stay physically unavailable; ending the event window does not reconstruct them. Closure and grid-outage durations can permit reopening/restoration if the later engine's state rules allow it. If one of these event definitions needs a different geographic interpretation, select Place/Region membership explicitly; there is no blast-radius or damage-mechanism calculation.

## Schema and edge direction

All nodes have stable `entity_id`, English `name`, `source`, `synthetic` and initial `status = 'operational'`. Located nodes also carry `city`, `place`, `region`, `country_code`, `latitude`, `longitude`, `geo_method` and `geo_synthetic`. The imported `id` property and internal TuringDB numeric ID are not the stable entity key.

The complete machine-readable property inventory is in the generated manifest's `schema.nodes` and `schema.edges`. Important relationships are:

| Relationship | Direction | Interpretation |
|---|---|---|
| `DEPENDS_ON` | Consumer → provider | Authoritative active dependency, with resource/group/logic/share |
| `SUPPLIES` | Provider → buyer | Annual-volume-weighted supply display projection |
| `POWERED_BY` | Facility → grid supply | Flattened power link for the existing map/cascade |
| `PRODUCED_AT` | Product/capability → facility | Where an item or service capability is produced |
| `SHIPPED_FROM`, `SHIPPED_TO` | Consignment → facility | Export input origin and receiving import-customs facility |
| `LOADED_AT`, `UNLOADED_AT` | Consignment → port | Baseline sea loading/unloading terminals |
| `TRANSITED` | Consignment → chokepoint | Baseline maritime exposure |
| `ROUTED_VIA` | Consignment → Route | Active baseline transport assignment |
| `CAN_USE` | Consignment → Route | Dormant alternative, activation/handling/cost data |
| `CARRIES` | Consignment → Component | Product class |
| `FULFILLS` | Consignment → Demand | Imported daily allocation |
| `NEEDS`, `REQUIRED_BY` | Demand → product/service | What is required, and by whom |
| `USES` | Route → terminal | Endpoint order; reverse this order for reverse-direction travel |
| `HAS_RECOVERY` | Asset → RecoveryOption | Candidate continuity action |
| `REQUIRES` | RecoveryOption → provider | Required physical resources; not an active dependency |
| `STORED_AT` | Stockpile → Facility | Inventory location, subject to regional loss |
| `DISABLES` | Scenario → asset | Initial event targets |
| `REPLENISHES`, `REPAIRS` | Sector service → infrastructure | Dormant delayed restoration links |
| `LOCATED_IN_PLACE` | Facility → Place | Town membership |
| `IN_REGION`, `IN_COUNTRY` | Place → Region/Country | Geographic scope |
| `LOCATED_IN`, `OPERATED_BY`, `SERVES` | Facility → Country/Company/Place | Ownership/location/beneficiary links |

Label-specific API keys are `facility_id`, `port_id`, `gppd_idnr`, `waypoint_id`, `platform_id` and `consignment_id`. They equal `entity_id` for those labels. `Platform.archetype` is a support-service classification; this graph has no weapon platform model.

Stable key examples:

```text
chokepoint:dover
route:tunnel
place:ashford
region:Kent
grid:ashford
infra:ashford:water_works
transport:ashford:road_hub
chain:uk_fr:medical:import_customs
chain:fr_uk:power:manufacturing
local:paris:medical:service
mission:ashford:military_hospital
capability:paris:nato_support_unit
consignment:uk_fr:medical
demand:paris:medical
reserve:ashford:cold
recovery:mission:ashford:military_hospital:relocate_service
```

## Contract for the future agent and scenario engine

1. Resolve a question to stable entities/places/regions and an abstract event kind. Keep interpretation separate from graph edits. No graph traversal or natural-language result needs to be restricted to the nine example scenarios.
2. Read `DEPENDS_ON` backwards to find dependents. Resource groups are required jointly: electricity plus water plus communications means all three are needed. Multiple `material_input` edges with `share` are a weighted mixture; the 60/40 edges are additive fractions, not independent full substitutes. A missing provider's share stays in the denominator.
3. Bound a consumer's capability by its weakest required resource group, its physical availability and throughput. `logic = 'required'` describes group-level obligation; shares describe contribution within the material-input group. Keep utility constraints separate from the weighted material mixture.
4. Move a simulation clock. Recurring consignments depart every 24 hours; honour activation, handling, transit, deadlines, shelf life and stock depletion. Waiting consumes reserves. A power outage may initially be masked by finite batteries or generators; catastrophic loss cannot be masked by stocks destroyed at the same location.
5. Evaluate dormant recovery candidates, including their providers' dependencies. Check compatibility, route endpoints, last-mile continuity and remaining shared resources before allocating. Splitting a delivery reserves tonnage on each route and its relevant handling/aircraft pools. `REQUIRES.quantity = 1` identifies a required provider; it is not a tonne allocation. Use consumption-specific fields and actual delivery tonnes.
6. General second-source capacity does not automatically repair electricity, communications or water. Its `resource_group = 'service_continuity'` concerns output/relocation. `release_stock` is scoped to consumables. Preserve separate physical-asset, utility and material state.
7. Use Demand priorities/minimums and programme requirements to report unmet service, delayed cargo, remaining stock, threatened hospitals and support capabilities. Programme dependencies represent service access, not an additional duplicate order for each already-counted Demand.
8. Create a branch from main, store replayable event/actions/allocations, and compare resulting states. TuringDB has no change-on-change: stack by replaying lineage into a new branch. Never submit an agent change to main. Keep the baseline unchanged.
9. Explain each consequence with its actual dependency path and each proposal with the required capacity, timing and shared resources. Label estimates as exercise assumptions. Do not claim that merely finding a recovery edge proves successful recovery.

This is a data contract, not an implementation of those steps. An allocator will still need explicit travel costs between town hubs, handling reservations, repairs, evacuation accounting, clock updates and resource conservation. The graph provides town positions and hub nodes, but does not assert calibrated domestic road travel times or railway schedules. Aircraft/tonnage abstraction is likewise an exercise assumption.

## Existing Impact viewer: useful but limited

The existing read-only cascade uses `SUPPLIES.annual_volume` and baseline consignments, rather than the full `DEPENDS_ON` logic. For Dover closure it seeds the twenty exporting input facilities and follows their supply projection through **12 degrees to 778 facilities**. This represents exposure of their exported supply flows; it does not mean all exporting factories physically stop when the sea closes. Downstream imported exposure becomes 60% after local supply is included. Programme projection averages inbound sector volumes, whereas a future scenario engine must respect required resource groups.

The viewer does not allocate alternatives, consume stock, handle regional simultaneous seeds, or simulate generator/aircraft limits. Its current flattened power edges are also not a complete substation/communications model. Do not reuse its displayed severity as a time-dependent clinical or military readiness forecast. The canonical dependency graph can extend beyond the viewer's 12-degree cap; the cap belongs to that UI/API projection, not the dataset.

The existing `/simulate` strike workflow is also theatre-oriented. For this dataset use the read-only Impact viewer for inspection and a later dedicated engine for event/recovery branches. The nine Scenario definitions are not executable API commands yet.

## Read-only query examples

Connect the SDK explicitly to port 6667 and graph `dover`:

```python
from turingdb import TuringDB
client = TuringDB(host="http://localhost:6667")
client.load_graph("dover", raise_if_loaded=False)
client.set_graph("dover")
client.checkout()
```

```cypher
-- Inspect the graph identity and provenance.
MATCH (d:Dataset) RETURN d.name, d.schema_version, d.seed, d.build_fingerprint

-- Discover all possible exercises and their initial targets.
MATCH (s:Scenario)-[:DISABLES]->(n)
RETURN s.entity_id, s.scenario_kind, s.duration_hours, n.entity_id LIMIT 200

-- Required resources for an Ashford hospital.
MATCH (f:Facility {entity_id: 'mission:ashford:military_hospital'})-[e:DEPENDS_ON]->(p)
RETURN e.resource, e.dependency_group, p.entity_id, p.name LIMIT 50

-- All consumers affected through up to sixteen canonical dependencies.
MATCH (o:Chokepoint {entity_id: 'chokepoint:dover'})<-[:DEPENDS_ON]-{1,16}(n)
RETURN DISTINCT n.entity_id, n.name LIMIT 2000

-- Provider requirements for hospital continuity.
MATCH (f:Facility {entity_id: 'mission:ashford:military_hospital'})-[:HAS_RECOVERY]->(r:RecoveryOption)-[:REQUIRES]->(p)
RETURN r.entity_id, r.recovery_kind, r.activation_hours, p.entity_id LIMIT 50

-- Delivery splitting possibilities and shared capacity.
MATCH (c:Consignment {entity_id: 'consignment:uk_fr:medical'})-[:CAN_USE]->(r:Route)
RETURN c.tonnes, r.entity_id, r.mode, r.capacity_tonnes_day, r.transit_hours LIMIT 20

-- Enumerate Kent physical grid sources, independently of English wording in a question.
MATCH (p:PowerPlant) WHERE p.region = 'Kent'
RETURN p.entity_id, p.name LIMIT 30
```

The Cypher snippets are intended for direct TuringDB 3.0 use. The existing agent read-query guard remains deliberately conservative and rejects some multi-match/variable-length syntax; a future agent should use typed tools or deliberately update that guard. No current agent is modified to answer these questions.

## Validation and files

`datasets/dover/model.py` defines the graph. `validate.py` checks isolation, bounds, identifiers, endpoints, graph-wide property types, dependency acyclicity, recovery coverage, independent crossings, baseline cargo balance, and 12-degree branching reach. `build.py` writes JSONL/manifest, imports the separate graph and checks every label and relationship count.

```bash
.venv/bin/python -m pytest tests/datasets/test_dover.py tests/api -q
DOVER_LIVE=1 .venv/bin/python -m pytest tests/datasets/test_dover_live.py -q
npm --prefix ui run typecheck
npm --prefix ui test
npm --prefix ui run build
```

Live validation is read-only and needs the dedicated server. It checks the graph identity, map reads, the real Dover cascade, dependency/recovery queries, and the absence of original agent routes. No Featherless request is required.
