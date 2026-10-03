# Deep Defense Supply Chain - TuringDB Graph

A **multi-tier defense supply chain** built to be *deep*: questions here routinely need
**5-12 hops**, from a weapon platform down through its bill of materials to the mine that
produces the raw mineral, across the facility-to-facility supplier network, up corporate
ownership chains, and over the maritime network through real chokepoints.

- **Graph name:** `supply_chain_deep`  ·  **Store:** [`graphs/supply_chain_deep/`](../graphs/supply_chain_deep)
- **Generator:** [`scripts/generate_supply_chain_deep.py`](../scripts/generate_supply_chain_deep.py) (deterministic, `--seed`, `--scale`)

## What is real and what is synthetic

| Real (approximate) reference data | Synthetic |
|---|---|
| Country shares of world mine production for 30 minerals, and of refining / processing for most materials (rounded, in the spirit of USGS Mineral Commodity Summaries 2024) | Platforms, systems, parts and part numbers |
| Which materials go into which (e.g. gallium is a by-product of alumina refining; germanium and indium come from zinc ore; nitrocellulose needs cotton linters) | Companies, facilities, cities assigned to them |
| 71 real ports, 15 chokepoints and 34 sea areas with coordinates; sea-lane distances from great-circle distance | Supplier links, ownership chains |
| NATO / EU membership; EU sanctions regimes (RUS, BLR, IRN) | 120,000 shipments (2023-2025) |
| 9 disruption events with their real dates: Red Sea attacks, Panama Canal drought, Chinese export controls on Ga/Ge, graphite, Sb, W/In/Mo, rare earths; EU sanctions on Russia | Effects of those events on shipments (reroutes, delays, blocked shipments) |

Company and product names are invented; any resemblance to real entities is coincidental.
Production shares are rounded orders of magnitude, good for analysis exercises, not for citation.

## Schema

### Nodes (132,834)

| Label | Count | Key | Properties |
|---|--:|---|---|
| `Platform` | 40 | `item_id` | `name`, `archetype` (e.g. Loitering munition, SHORAD system, 155mm artillery round), `level`=0, `unit_cost_eur`, `lead_time_days`, `annual_demand` |
| `System` | 208 | `item_id` | `name`, `category` (domain: Guidance & navigation, Radar, Warhead & fuzing, ...), `level`=1, `unit_cost_eur`, `lead_time_days`, `criticality` |
| `Subsystem` | 252 | `item_id` | same as above, `level`=2 (shared across platforms) |
| `Assembly` | 761 | `item_id` | same, `level`=3 |
| `Subassembly` | 880 | `item_id` | same, `level`=4 (shared pools: PCB assembly, RF front-end, IR optical train, rocket motor, ...) |
| `Component` | 1,532 | `item_id` | `name`, `family` (e.g. GaN power amplifier MMIC, Li-ion cell (21700)), `category`, `level`=5, `unit_cost_eur`, `lead_time_days`, `export_controlled`, `criticality` |
| `Material` | 80 | `item_id` | `name` (e.g. High-purity gallium (6N), Sintered NdFeB magnet, Nitrocellulose), `category`, `level`=6, `unit_cost_eur`, `lead_time_days` |
| `Mineral` | 30 | `item_id` | `name` (e.g. Bauxite, Rare earth ore, Coltan), `level`=7, `top_producer`, `top_producer_share_pct` |
| `Facility` | 4,404 | `facility_id` | `name`, `facility_type` (final assembly plant ... component fab, processing plant, mine, trading / distribution hub), `tier` (0 = prime ... 7 = mine), `sector`, `city`, `country_code`, `capacity_utilization` |
| `Company` | 4,451 | `company_id` | `name`, `company_type` (operating / holding), `tier`, `sector`, `hq_country` |
| `Country` | 67 | `country_code` | `name`, `region`, `nato_member`, `eu_member`, `eu_sanctions_target` |
| `Port` | 71 | `port_id` | `name`, `lat`, `lon`, `country_code` |
| `Chokepoint` | 15 | `waypoint_id` | `name` (Strait of Hormuz, Bab-el-Mandeb, Taiwan Strait, ...), `lat`, `lon` |
| `SeaArea` | 34 | `waypoint_id` | `name`, `lat`, `lon` (open-sea routing waypoints) |
| `Shipment` | 120,000 | `shipment_id` | `ship_date`, `arrival_date`, `mode` (sea / air / road / rail/road), `status` (delivered / in_transit / blocked), `qty`, `value_eur`, `planned_transit_days`, `actual_transit_days`, `delay_days`, `rerouted`, `route` |
| `Disruption` | 9 | `disruption_id` | `name`, `kind` (maritime / export-control / sanctions), `start_date`, `end_date`, `description` |

Every node has a `name` display property used as the label in the TuringDB visualizer.

### Edges (763,831)

| Edge | From → To | Count | Meaning |
|---|---|--:|---|
| `CONTAINS` | item → item | 10,200 | Bill of materials, one level down (`qty`, `unit`). Platform → System → Subsystem → Assembly → Subassembly → Component → Material (1-4 processing steps) → Mineral |
| `PRODUCED_AT` | item → `Facility` | 7,141 | Where an item is made (`share_pct`) |
| `PRODUCTION_SHARE` | `Mineral`/`Material` → `Country` | 624 | Real-world country share of production (`share_pct`, `basis`) |
| `SUPPLIES` | `Facility` → `Facility` | 21,048 | Physical supply link (`item_id`, `annual_volume`), mine → refinery → ... → prime |
| `OPERATED_BY` | `Facility` → `Company` | 4,404 | Operator |
| `LOCATED_IN` | `Facility`/`Port` → `Country` | 4,475 | Location |
| `HEADQUARTERED_IN` | `Company` → `Country` | 4,451 | Company HQ / jurisdiction |
| `SUBSIDIARY_OF` | `Company` → `Company` | 1,702 | Ownership (`ownership_pct`), chains up to 8 levels through holdings in LUX, NLD, IRL, CYP, CHE, VGB, HKG, SGP, ARE |
| `SHIPS_VIA` | `Facility` → `Port` | 4,404 | Export gateway (`mode`, `inland_km`); landlocked countries use a neighbour's port |
| `SEA_LANE` | `Port`/`SeaArea`/`Chokepoint` ↔ same | 322 | Maritime network, both directions (`distance_nm`, `transit_days`) |
| `SHIPPED_FROM` / `SHIPPED_TO` | `Shipment` → `Facility` | 120,000 each | Origin / destination facility |
| `CARRIES` | `Shipment` → item | 120,000 | What was shipped |
| `LOADED_AT` / `UNLOADED_AT` | `Shipment` → `Port` | 73,809 each | Sea shipments only |
| `TRANSITED` | `Shipment` → `Chokepoint` | 170,808 | Chokepoints on the actual route (`seq`) |
| `IMPACTED_BY` | `Shipment` → `Disruption` | 26,607 | Shipment was rerouted, delayed or blocked by the event |
| `AFFECTS` | `Disruption` → `Chokepoint`/`Material`/`Mineral`/`Country` | 27 | What the event targets |

### Shape

```
Platform -CONTAINS-> System -CONTAINS-> Subsystem -CONTAINS-> Assembly -CONTAINS-> Subassembly
   -CONTAINS-> Component -CONTAINS-> Material -CONTAINS->(1-4x) Mineral -PRODUCTION_SHARE-> Country
      |                                                            |
  PRODUCED_AT                                                  PRODUCED_AT
      v                                                            v
  Facility (prime) <-SUPPLIES- ... <-SUPPLIES- Facility <-SUPPLIES- Facility (mine)
      |  OPERATED_BY -> Company -SUBSIDIARY_OF->+ Company (ultimate parent) -HEADQUARTERED_IN-> Country
      |  SHIPS_VIA -> Port -SEA_LANE-> SeaArea / Chokepoint -SEA_LANE-> ... -> Port
      |
  Shipment -SHIPPED_FROM/TO-> Facility, -CARRIES-> item, -TRANSITED-> Chokepoint, -IMPACTED_BY-> Disruption
```

Typical depths: a platform reaches its minerals in **8** `CONTAINS` hops (10 with the mine and
its country); mine → prime-contractor supply chains are **6-9** `SUPPLIES` hops; ownership
chains go up to **8** levels; Shanghai → Rotterdam is **~18** sea-lane hops.

## What it enables

- **Deep dependency mapping** - which platforms ultimately depend on Chinese gallium,
  Congolese cobalt or Russian titanium, through any number of tiers.
- **Hidden concentration** - single facilities or companies that many supply chains converge on.
- **Ownership & sanctions risk** - NATO/EU suppliers whose ultimate parent sits in China or a
  sanctioned country, behind layers of holding companies; Russian supply reaching EU buyers
  through third-country traders.
- **Chokepoint & disruption analysis** - Red Sea reroutes around the Cape, Panama drought delays,
  export-control licence delays and blocked shipments; "what if the Taiwan Strait closes?"
- **Lead-time & critical-path analysis** along the bill of materials.

The graph also contains a few **planted findings** for teams to discover (a hidden single point
of failure, foreign-ownership chains, sanctions exposure). Organizers can see them in the
generator output.

## Quick start

```bash
# from the repo root
uv run turingdb start -turing-dir "$(pwd)" -ui
```

```python
from turingdb import TuringDB
c = TuringDB(host="http://localhost:6666")
c.load_graph("supply_chain_deep"); c.set_graph("supply_chain_deep")
```

### Starter queries

Variable-length paths use a postfix quantifier and can be typed: `-[:CONTAINS]->+`,
`-[:SUPPLIES]->{6,9}`. Sea lanes are cyclic, so **bound** `SEA_LANE` traversals or use
`shortestPath`.

```cypher
-- 1. Explode a bill of materials: platform -> raw minerals, exactly 8 hops
MATCH (p:Platform {archetype:'Loitering munition'})-[:CONTAINS]->{8,8}(m:Mineral)
RETURN DISTINCT p.name, m.name

-- 2. Every platform that ultimately depends on primary gallium (any depth)
MATCH (p:Platform)-[:CONTAINS]->+(:Material {name:'Primary gallium'})
RETURN DISTINCT p.name, p.archetype

-- 3. A platform's mineral exposure to China, with real production shares
MATCH (p:Platform {archetype:'Air-defense interceptor'})-[:CONTAINS]->+(m:Mineral)
      -[ps:PRODUCTION_SHARE]->(:Country {country_code:'CHN'})
RETURN DISTINCT p.name, m.name, ps.share_pct ORDER BY ps.share_pct DESC

-- 4. Physical supply chains from DR Congo mines to prime contractors (6-9 tiers)
MATCH (:Country {country_code:'COD'})<-[:LOCATED_IN]-(mine:Facility {facility_type:'mine'})
      -[:SUPPLIES]->{6,9}(prime:Facility {facility_type:'final assembly plant'})
RETURN DISTINCT mine.name, prime.name

-- 5. Companies headquartered in NATO countries whose ultimate parent is Chinese
MATCH (:Country {nato_member:true})<-[:HEADQUARTERED_IN]-(c:Company)
      -[:SUBSIDIARY_OF]->+(u:Company {hq_country:'CHN'})
RETURN DISTINCT c.name, c.hq_country, u.name

-- 6. Facilities owned (at any depth) by a company in a sanctioned country that supply NATO buyers
MATCH (f:Facility)-[:OPERATED_BY]->(:Company)-[:SUBSIDIARY_OF]->+(u:Company)
      -[:HEADQUARTERED_IN]->(:Country {eu_sanctions_target:true}),
      (f)-[:SUPPLIES]->(b:Facility)-[:LOCATED_IN]->(:Country {nato_member:true})
RETURN DISTINCT f.name, u.name, b.name

-- 7. Russian supply reaching EU buyers through third-country trading hubs
MATCH (r:Facility {country_code:'RUS'})-[:SUPPLIES]->(t:Facility {facility_type:'trading / distribution hub'})
      -[:SUPPLIES]->(b:Facility)-[:LOCATED_IN]->(:Country {eu_member:true})
RETURN DISTINCT r.name, t.name, t.country_code, b.name

-- 8. Shortest sea route Shanghai -> Rotterdam (nautical miles)
MATCH (a:Port {port_id:'CNSHA'}), (b:Port {port_id:'NLRTM'})
shortestPath(a, b, distance_nm, dist, path)
RETURN dist, path

-- 9. Red Sea effect: delay of rerouted vs. normal sea shipments since 19 Nov 2023
MATCH (s:Shipment {mode:'sea'})
WHERE s.ship_date >= '2023-11-19' AND s.delay_days IS NOT NULL
RETURN s.rerouted, count(s), avg(s.delay_days)

-- 10. Prime contractors downstream of anything shipped through the Taiwan Strait
MATCH (s:Shipment)-[:TRANSITED]->(:Chokepoint {name:'Taiwan Strait'}),
      (s)-[:SHIPPED_TO]->(f:Facility)-[:SUPPLIES]->+(prime:Facility {facility_type:'final assembly plant'})
RETURN DISTINCT prime.name

-- 11. Component concentration: facilities making the most part numbers
MATCH (c:Component)-[:PRODUCED_AT]->(f:Facility)
RETURN f.name, f.country_code, count(c) AS parts ORDER BY parts DESC LIMIT 10

-- 12. Shipments blocked by export controls
MATCH (s:Shipment {status:'blocked'})-[:CARRIES]->(m), (s)-[:IMPACTED_BY]->(d:Disruption)
RETURN m.name, d.name, count(s)

-- 13. Longest cumulative lead time along a 6-level BOM path
MATCH (p:Platform {archetype:'Cruise missile'})-[:CONTAINS]->(s:System)-[:CONTAINS]->(ss:Subsystem)
      -[:CONTAINS]->(a:Assembly)-[:CONTAINS]->(sa:Subassembly)-[:CONTAINS]->(c:Component)
RETURN p.name, c.name,
       p.lead_time_days + s.lead_time_days + ss.lead_time_days + a.lead_time_days
       + sa.lead_time_days + c.lead_time_days AS total
ORDER BY total DESC LIMIT 5
```

## Regenerating / resizing

```bash
uv run scripts/generate_supply_chain_deep.py --out /tmp/scd --seed 7 --scale 1.0 --shipments 120000
uv run turing-parquet -nodes /tmp/scd/nodes.parquet -edges /tmp/scd/edges.parquet \
                      -out /tmp/scd/turing -graph supply_chain_deep < /dev/null
cp -r /tmp/scd/turing/graphs/supply_chain_deep graphs/
```

`--scale` multiplies the part-number pools, platform variants and shipment count; the planted
findings are listed in the generator output and in `/tmp/scd/planted_findings.txt`.

## License

Generated data and generator released under the **[MIT License](https://opensource.org/license/mit)**.
Reference figures (mineral production shares, port and chokepoint locations, event dates) are
approximations of public information.

*Platforms, companies, facilities, ownership and shipments are fully synthetic and do not
represent any real company or program.*
