# Theatre - fused defence operating picture

`theatre` fuses all six bundled graphs into one TuringDB graph built for a red-vs-blue agent war game.
It answers questions like *"if this power plant / supplier / corridor is hit, which sites and parts
lose supply, and who nearby could be an insider threat?"*. Competing intelligence hypotheses are meant to
live on TuringDB changes (branches) on top of it.

- **Graph name:** `theatre`  ·  **Store:** `graphs/theatre/` (generated, ~0.3 GB JSONL intermediate in `data/`)
- **Build:** `uv run python fusion/build_theatre.py` (idempotent, ~25 s, seed `20261002`)
- **Queries + timings:** `uv run python fusion/theatre_queries.py` (rewrites the *Example queries* block below)
- **Versioning demo:** `uv run python fusion/versioning_demo.py` (rewrites the *Versioning demo* block below)
- **Engine:** pinned to `turingdb==1.37`. The bundled graphs were written by 1.37; `turingdb` 3.0
  (released 2026-10-02) refuses to load them ("File outdated").

> **Update (turingdb 3.0 + `supply_chain_deep`).** The repo now pins `turingdb==3.0` and `theatre` fuses a
> seventh source, `supply_chain_deep` (426,969 nodes / 1,621,798 edges after the report commits). Deep
> facilities are geocoded from their city (`fusion/deep_geo.py`, jittered, `geo_synthetic`) and bridged to
> their 3 nearest plants (`POWERED_BY`); the deep `Shipment` label is renamed `Consignment`; `Country` gains
> HKG and VGB. `graphs/theatre/` is generated and not tracked in git (a 3.0 store file exceeds GitHub's
> 100 MB limit). Counts, queries and the 1.37 caveats below predate this update; most of those caveats are
> lifted in 3.0 (see AGENTS.md).

The source graphs are only read, never written. Everything invented is marked: nodes/edges with
`synthetic: true`, invented coordinates with `geo_synthetic: true`.

## Build pipeline

1. **Extract** every label and edge type of the six graphs with all properties (`fusion/extract.py`),
   checking the exported totals against `count()` in each graph.
2. **Real join** - `Country`: power_plants (ISO3 `country_code` + `name`) and logistics_risk (`name`)
   merge into one node per country. Names are normalised (case, accents, punctuation) plus four
   explicit synonyms (`UK`, `USA`, `UAE`, `North Macedonia` -> GPPD spellings). 93 of 94 logistics names match;
   **`Haiti` does not** (power_plants has no Haiti), so it stays a logistics-only `Country` with no ISO3.
3. **Keep every original node and edge.** `Supplier` exists in two sources, so its key value is prefixed
   with the source (`supply_chain:SUP012`, `logistics_risk:P0023_S1`; raw value kept in `local_id`).
   Every node and edge carries `source` (`power_plants`, `supply_chain`, ..., `theatre` for bridges, `intel`
   for reports). TuringDB property types are graph-global, so three originals were renamed:
   `PowerPlant.source` and `Attack.source` -> `data_source`, `Reading.timestamp` (step index) -> `timestep`.
   `Part.lead_time_days` (Int64) is cast to Double to match `Shipment.lead_time_days`.
4. **Time and location.** Every event gets an ISO `timestamp` plus an integer `ts_epoch` (1.37 cannot
   compare strings with `<`/`>`, so range filters use `ts_epoch`). Coordinates are added wherever a node has a
   location; `geo_method` says how.
5. **Synthetic bridges** with a fixed seed (`fusion/bridges.py`, `fusion/links.py`).
6. **Load** as a new graph via `LOAD JSONL` (commit 1), verify every label/edge count and key property types.
7. **Intelligence layer** - 21 hand-written reports committed in 3 changes (commits 2-4).

## Schema

### Nodes (294,200 after the report batches)

| Label | Source | Key | Count | Added in theatre |
|---|---|---|--:|---|
| `PowerPlant` | power_plants | `gppd_idnr` | 34,936 | `source` (orig. `source` -> `data_source`) |
| `Country` | power_plants + logistics_risk (merged) | `country_code` (ISO3; `name` for Haiti) | 168 | `logistics_name`, lat/lon = median of its plants |
| `Fuel` / `Owner` | power_plants | `name` | 15 / 10,144 | |
| `Site` | supply_chain | `site_id` | 6 | **synthetic** lat/lon, `place`, `country_code` |
| `Supplier` (part suppliers) | supply_chain | `supplier_id` = `supply_chain:SUPnnn` | 40 | **synthetic** lat/lon, `place`, `country_code` |
| `Part` | supply_chain | `part_id` | 300 | `lead_time_days` as Double |
| `PurchaseOrder` | supply_chain | `po_id` | 29,666 | `timestamp` / `ts_epoch` from `order_date` |
| `QualityIncident` | supply_chain | `incident_id` | 368 | `timestamp` / `ts_epoch` from `incident_date` |
| `Supplier` (logistics) | logistics_risk | `supplier_id` = `logistics_risk:Pnnnn_Sn` | 3,524 | |
| `Shipment` | logistics_risk | `shipment_id` | 113,097 | (no date in the source, so no timestamp) |
| `Product` / `RiskClassification` | logistics_risk | `product_id` / `name` | 1,000 / 3 | |
| `Drone` | drone_swarm | `drone_id` | 20 | **synthetic** lat/lon of last reading |
| `Reading` | drone_swarm | `reading_id` | 20,000 | **synthetic** lat/lon from x/y; `timestamp` = 2026-09-29T05:00Z + 5 s x `timestep` |
| `TimeStep` / `FormationPattern` / `MissionStatus` | drone_swarm | `t` / `name` / `name` | 1,000 / 4 / 4 | |
| `Location` | poledb | node identity (`address` has 987 duplicates) | 14,904 | |
| `Crime` | poledb | `id` | 28,762 | lat/lon from its `Location`; `timestamp` from `date` |
| `PhoneCall` | poledb | - | 534 | `timestamp` from `call_date` + `call_time` |
| `Person` | poledb | `nhs_no` | 369 | lat/lon from `CURRENT_ADDRESS` |
| `PostCode` / `Area` | poledb | `code` / `areaCode` | 14,196 / 93 | lat/lon = mean of their Locations |
| `Officer`, `Vehicle`, `Phone`, `Email`, `Object` | poledb | as in poledb | 1,000 / 1,000 / 328 / 328 / 7 | |
| `Attack` | attack_scenarios | `attack_id` | 14,133 | orig. `source` -> `data_source` |
| `MitreTechnique` / `Tool` / `Category` | attack_scenarios | `code` / `name` / `name` | 918 / 3,240 / 63 | |
| `AssetType` | theatre | `asset_type_id` | 9 | **synthetic** (ICS/SCADA, OT network, ERP, Logistics IT, Corporate IT, Software supply chain, SATCOM/GNSS, UAS avionics, Physical access control) |
| `Report` | intel | `report_id` | 21 | **synthetic**: `text`, `timestamp`, `ts_epoch`, `latitude`, `longitude`, `source_type`, `confidence`, `claim`, `batch` |

`geo_method` values: `synthetic_placement` (Site, part Supplier), `synthetic_projection` (Reading),
`last_reading` (Drone), `from_location` (Crime, Person), `mean_of_locations` (PostCode, Area),
`median_of_power_plants` (Country). PowerPlant and Location keep their original coordinates.

### Edges (845,561 after the report batches)

| Edge | From -> To | Count | Synthetic | Notes |
|---|---|--:|---|---|
| all original edge types | as in the source docs | 738,696 | no | `source` = origin dataset; `NEAR` keeps `distance_km`, `FAMILY_REL` keeps `rel_type` |
| `LOCATED_IN` | PowerPlant / logistics Supplier -> Country | 34,936 + 3,524 | no | re-pointed to the merged Country |
| `LOCATED_IN` | Site / part Supplier -> Country | 6 + 40 | **yes** | follows the synthetic placement |
| `POWERED_BY` | Site / part Supplier -> PowerPlant | 138 | **yes** | 3 nearest plants within 50 km, `distance_km` (all 46 entities got 3) |
| `SOURCES_FROM` | part Supplier -> logistics Supplier | 81 | **yes** | 1-3 logistics suppliers in the same Country |
| `PATROLS` | Drone -> Site | 20 | **yes** | the whole swarm patrols SITE01, `mission: 'ISR'` |
| `NEAR` | Location -> Site | 1,653 | **yes** | <= 5 km, `distance_km` (all at SITE01: poledb is Greater Manchester) |
| `NEAR` | Location -> PowerPlant | 23,171 | no (`synthetic: false`) | <= 5 km from real coordinates, 37 distinct plants |
| `TARGETS` | Attack -> AssetType | 4,589 | **yes** | keyword match on `target_type` + `tags`, `keyword` = matched word; 4,383 of 14,133 attacks |
| `RUNS` | PowerPlant / Site / Supplier / Drone -> AssetType | 77,110 | **yes** | plants: ICS/SCADA + OT; sites: ICS, OT, ERP, Corporate IT, Physical access; part suppliers: ERP, Corporate IT, SW supply chain; logistics suppliers: Logistics IT, ERP; drones: UAS avionics, SATCOM/GNSS |
| `MENTIONS` | Report -> PowerPlant / Site / Supplier / Person / Drone / AssetType | 51 | **yes** | |
| `CONTRADICTS` | later Report -> earlier Report | 6 | **yes** | seeds competing hypothesis branches |

### Synthetic placements

| Site | Placed at | Country |
|---|---|---|
| SITE01 | Trafford Park, Manchester (ISR swarm patrol, poledb overlap) | GBR |
| SITE02 | Warton, Lancashire | GBR |
| SITE03 | Toulouse-Blagnac | FRA |
| SITE04 | Hamburg-Finkenwerder | DEU |
| SITE05 | Seville San Pablo | ESP |
| SITE06 | Rzeszow-Jasionka | POL |

The 40 part suppliers are shuffled onto 40 towns in 16 NATO-Europe countries (6 in the UK, then FRA, DEU,
ITA, ESP, POL, NLD, BEL, SWE, NOR, CZE, ROU, FIN, DNK, AUT, PRT), with up to 5 km of seeded jitter
(sites: 1.5 km). Drone x/y units are projected at 20 m per unit around SITE01 (about 2.5 km box).

### Intelligence reports

21 reports from `drone`, `OSINT`, `HUMINT` and `SIGINT` sources, 28 Sep - 1 Oct 2026, committed in 3 batches.
Six contradicting pairs (`later -[:CONTRADICTS]-> earlier`):

| Earlier | Later | Dispute |
|---|---|---|
| RPT-01 (OSINT 0.55, struck) | RPT-08 (SIGINT 0.80, operational) | Wedel power station, which feeds SITE04 |
| RPT-02 (drone 0.70, breach) | RPT-09 (drone 0.65, no breach) | SITE01 west fence |
| RPT-03 (HUMINT 0.50, insider lead) | RPT-10 (HUMINT 0.70, cleared) | a resident of 54 Barton Street, 4 km from SITE01 |
| RPT-05 (OSINT 0.60, disrupted) | RPT-13 (SIGINT 0.70, operational) | Port of Barcelona / supplier SUP012 |
| RPT-07 (OSINT 0.60, operational) | RPT-14 (OSINT 0.50, damaged) | Lockleaze Energy Storage, backing SUP032 |
| RPT-17 (SIGINT 0.60, offline) | RPT-18 (OSINT 0.70, operational) | EC Rzeszow, which feeds SITE06 |

## Example queries

All eight are **single linear paths**: in 1.37, comma-separated patterns joined on a shared variable return
wrong results or hang the server (see *TuringDB 1.37 caveats*). Q1 and Q6 were cross-checked against a
pandas join of single-hop queries and match exactly (3,327 and 147 rows).

<!-- EXAMPLE_QUERIES:START -->
Generated by `fusion/theatre_queries.py` against the current `theatre` HEAD with `turingdb` 1.37. Latency is server-side execution time (`client.get_query_exec_time()`): first run, and the median of 5 warm runs.

| Query | Question | Source datasets crossed | Rows | First run (ms) | Warm median (ms) |
|---|---|---|--:|--:|--:|
| Q1 | Energy -> supply cascade (8 hops) | power_plants, supply_chain, logistics_risk | 3,327 | 41.7 | 13.2 |
| Q2 | Cyber kill chain to a physical asset | supply_chain, power_plants, attack_scenarios | 1,500 | 27.0 | 11.4 |
| Q3 | Sabotage leads | supply_chain, power_plants, poledb | 85 | 8.4 | 6.4 |
| Q4 | Insider leads | power_plants, supply_chain, poledb | 19 | 9.7 | 6.7 |
| Q5 | Gas-fired dependency | power_plants, supply_chain, logistics_risk | 457 | 19.5 | 15.2 |
| Q6 | ISR cross-check | drone_swarm, supply_chain, power_plants | 147 | 11.9 | 10.3 |
| Q7 | Hypothesis board | power_plants, supply_chain, intel | 3 | 0.8 | 0.1 |
| Q8 | Counter-UAS | attack_scenarios, drone_swarm, supply_chain | 1,520 | 8.7 | 8.3 |

### Q1. Energy -> supply cascade (8 hops): Wedel power station -> SITE04 -> recent POs -> class-A parts -> their primary suppliers -> logistics suppliers -> high-risk shipments

Crosses: `power_plants`, `supply_chain`, `logistics_risk`. 3,327 rows, 13.2 ms warm.

```cypher
MATCH (pp:PowerPlant {gppd_idnr:'WRI1006130'})<-[:POWERED_BY]-(s:Site)<-[:DELIVERED_TO]-(po:PurchaseOrder)-[:FOR_PART]->(pt:Part)-[:SUPPLIED_BY]->(sup:Supplier)-[:SOURCES_FROM]->(ls:Supplier)<-[:FROM_SUPPLIER]-(sh:Shipment)-[:CLASSIFIED_AS]->(rc:RiskClassification {name:'High Risk'})
WHERE pt.criticality_class = 'A' AND po.ts_epoch >= 1719792000
RETURN pp.name, s.site_id, po.po_id, pt.part_id, sup.supplier_id, ls.supplier_id, sh.shipment_id, sh.delay_probability
```

<details><summary>First 3 rows</summary>

| pp.name             | s.site_id   | po.po_id   | pt.part_id   | sup.supplier_id     | ls.supplier_id          | sh.shipment_id   |   sh.delay_probability |
|:--------------------|:------------|:-----------|:-------------|:--------------------|:------------------------|:-----------------|-----------------------:|
| Wedel power station | SITE04      | PO015379   | P00155       | supply_chain:SUP013 | logistics_risk:P0664_S4 | INST048474       |               0.999548 |
| Wedel power station | SITE04      | PO015379   | P00155       | supply_chain:SUP013 | logistics_risk:P0664_S4 | INST079770       |               0.678729 |
| Wedel power station | SITE04      | PO015379   | P00155       | supply_chain:SUP013 | logistics_risk:P0664_S4 | INST084630       |               1        |

</details>

### Q2. Cyber kill chain to a physical asset: ICS attacks and MITRE techniques against the plants powering SITE01

Crosses: `supply_chain`, `power_plants`, `attack_scenarios`. 1,500 rows, 11.4 ms warm.

```cypher
MATCH (s:Site {site_id:'SITE01'})-[:POWERED_BY]->(pp:PowerPlant)-[:RUNS]->(at:AssetType {asset_type_id:'ICS_SCADA'})<-[:TARGETS]-(a:Attack)-[:USES_TECHNIQUE]->(t:MitreTechnique)
RETURN pp.name, a.name, a.attack_type, t.code, t.name
```

<details><summary>First 3 rows</summary>

| pp.name                                                     | a.name                                                   | a.attack_type                        | t.code    | t.name                                                  |
|:------------------------------------------------------------|:---------------------------------------------------------|:-------------------------------------|:----------|:--------------------------------------------------------|
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | IEC 104 Data Injection to Falsify Alarm                  | IEC 104 Alarm Injection              | T1565.001 | DNS Manipulation) (Man-in-the-Middle) (Network Sniffing |
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | Backdoored Vendor Update Disk via Logistics Interception | Supply Chain / Physical Interception | T1200     | – Access Control Violation                              |
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | Log File Manipulation to Hide Attack Traces              | HMI Exploitation                     | T1070.001 | – Indicator Removal on Host                             |

</details>

### Q3. Sabotage leads: criminal damage and arson within 1 km of the plants feeding SITE01

Crosses: `supply_chain`, `power_plants`, `poledb`. 85 rows, 6.4 ms warm.

```cypher
MATCH (s:Site {site_id:'SITE01'})-[:POWERED_BY]->(pp:PowerPlant)<-[n:NEAR]-(l:Location)<-[:OCCURRED_AT]-(cr:Crime)
WHERE cr.`type` = 'Criminal damage and arson' AND n.distance_km < 1.0
RETURN pp.name, l.address, n.distance_km, cr.timestamp, cr.last_outcome
```

<details><summary>First 3 rows</summary>

| pp.name                                                     | l.address             |   n.distance_km | cr.timestamp         | cr.last_outcome                               |
|:------------------------------------------------------------|:----------------------|----------------:|:---------------------|:----------------------------------------------|
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | 163 Kirkstead Close   |           0.85  | 2017-08-15T00:00:00Z | Investigation complete; no suspect identified |
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | 164 Hinckley Street   |           0.598 | 2017-08-23T00:00:00Z | Unable to prosecute suspect                   |
| Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) | 87 Clydesdale Gardens |           0.978 | 2017-08-31T00:00:00Z | Investigation complete; no suspect identified |

</details>

### Q4. Insider leads: residents near a site that depends on Salford Refuse Treatment Plant whose known associates are party to crimes

Crosses: `power_plants`, `supply_chain`, `poledb`. 19 rows, 6.7 ms warm.

```cypher
MATCH (pp:PowerPlant {gppd_idnr:'GBR0000912'})<-[:POWERED_BY]-(s:Site)<-[n:NEAR]-(l:Location)<-[:CURRENT_ADDRESS]-(p:Person)-[:KNOWS]-(a:Person)-[:PARTY_TO]->(cr:Crime)
RETURN s.site_id, p.name, p.surname, l.address, n.distance_km, a.name, a.surname, cr.`type`, cr.timestamp
```

<details><summary>First 3 rows</summary>

| s.site_id   | p.name   | p.surname   | l.address       |   n.distance_km | a.name   | a.surname   | cr.`type`   | cr.timestamp         |
|:------------|:---------|:------------|:----------------|----------------:|:---------|:------------|:------------|:---------------------|
| SITE01      | William  | Dixon       | 85 Ordsall Lane |           2.472 | Jack     | Powell      | Drugs       | 2017-08-27T00:00:00Z |
| SITE01      | William  | Dixon       | 85 Ordsall Lane |           2.472 | Jack     | Powell      | Drugs       | 2017-08-02T00:00:00Z |
| SITE01      | William  | Dixon       | 85 Ordsall Lane |           2.472 | Jack     | Powell      | Drugs       | 2017-08-25T00:00:00Z |

</details>

### Q5. Gas-fired dependency: part suppliers powered by gas plants whose logistics partners show delay probability > 0.9

Crosses: `power_plants`, `supply_chain`, `logistics_risk`. 457 rows, 15.2 ms warm.

```cypher
MATCH (f:Fuel {name:'Gas'})<-[:PRIMARY_FUEL]-(pp:PowerPlant)<-[:POWERED_BY]-(sup:Supplier)-[:SOURCES_FROM]->(ls:Supplier)<-[:FROM_SUPPLIER]-(sh:Shipment)
WHERE sh.delay_probability > 0.9
RETURN sup.supplier_id, sup.place, sup.country_code, pp.name, pp.capacity_mw, ls.supplier_id, sh.shipment_id, sh.delay_probability
```

<details><summary>First 3 rows</summary>

| sup.supplier_id     | sup.place   | sup.country_code   | pp.name   |   pp.capacity_mw | ls.supplier_id          | sh.shipment_id   |   sh.delay_probability |
|:--------------------|:------------|:-------------------|:----------|-----------------:|:------------------------|:-----------------|-----------------------:|
| supply_chain:SUP034 | Gothenburg  | SWE                | Rya       |              261 | logistics_risk:P0020_S2 | INST062480       |               0.999993 |
| supply_chain:SUP034 | Gothenburg  | SWE                | Rya       |              261 | logistics_risk:P0020_S2 | INST060734       |               0.993659 |
| supply_chain:SUP034 | Gothenburg  | SWE                | Rya       |              261 | logistics_risk:P0020_S2 | INST105974       |               0.992638 |

</details>

### Q6. ISR cross-check: collision-warning readings of drones named in drone reports about a site, and the plants that power that site

Crosses: `drone_swarm`, `supply_chain`, `power_plants`. 147 rows, 10.3 ms warm.

```cypher
MATCH (rd:Reading)-[:OF_DRONE]->(d:Drone)<-[:MENTIONS]-(r:Report)-[:MENTIONS]->(s:Site)-[:POWERED_BY]->(pp:PowerPlant)
WHERE r.source_type = 'drone' AND rd.collision_warning = 1
RETURN r.report_id, r.claim, d.drone_id, rd.timestamp, rd.latitude, rd.longitude, s.site_id, pp.name
```

<details><summary>First 3 rows</summary>

| r.report_id   | r.claim   |   d.drone_id | rd.timestamp         |   rd.latitude |   rd.longitude | s.site_id   | pp.name                                                     |
|:--------------|:----------|-------------:|:---------------------|--------------:|---------------:|:------------|:------------------------------------------------------------|
| RPT-02        | breach    |            3 | 2026-09-29T05:04:35Z |       53.4655 |       -2.32665 | SITE01      | Ardwick Railway Goods Yard Incinerator (Newhaven EFW Plant) |
| RPT-02        | breach    |            3 | 2026-09-29T05:04:35Z |       53.4655 |       -2.32665 | SITE01      | Clifton Hall                                                |
| RPT-02        | breach    |            3 | 2026-09-29T05:04:35Z |       53.4655 |       -2.32665 | SITE01      | Salford Refuse Treatment Plant (AD)                         |

</details>

### Q7. Hypothesis board: contradicting report pairs about power plants and every Site or Supplier that depends on the disputed plant

Crosses: `power_plants`, `supply_chain`, `intel`. 3 rows, 0.1 ms warm.

```cypher
MATCH (later:Report)-[:CONTRADICTS]->(earlier:Report)-[:MENTIONS]->(pp:PowerPlant)<-[e:POWERED_BY]-(x)
RETURN earlier.report_id, earlier.claim, earlier.confidence, later.report_id, later.claim, later.confidence, pp.name, labels(x), x.name, e.distance_km
```

<details><summary>First 3 rows</summary>

| earlier.report_id   | earlier.claim   |   earlier.confidence | later.report_id   | later.claim   |   later.confidence | pp.name                  | labels(x)   | x.name           |   e.distance_km |
|:--------------------|:----------------|---------------------:|:------------------|:--------------|-------------------:|:-------------------------|:------------|:-----------------|----------------:|
| RPT-01              | struck          |                 0.55 | RPT-08            | operational   |                0.8 | Wedel power station      | Site        | Site: SITE04     |           8.08  |
| RPT-07              | operational     |                 0.6  | RPT-14            | damaged       |                0.5 | Lockleaze Energy Storage | Supplier    | Supplier: SUP032 |           1.815 |
| RPT-17              | offline         |                 0.6  | RPT-18            | operational   |                0.7 | EC Rzeszów               | Site        | Site: SITE06     |           5.015 |

</details>

### Q8. Counter-UAS: attack scenarios (and their tools) that target the avionics of the ISR swarm patrolling SITE01

Crosses: `attack_scenarios`, `drone_swarm`, `supply_chain`. 1,520 rows, 8.3 ms warm.

```cypher
MATCH (t:Tool)<-[:USES_TOOL]-(a:Attack)-[:TARGETS]->(at:AssetType {asset_type_id:'UAS_AVIONICS'})<-[:RUNS]-(d:Drone)-[:PATROLS]->(s:Site)
RETURN s.site_id, d.drone_id, a.name, a.attack_type, t.name
```

<details><summary>First 3 rows</summary>

| s.site_id   |   d.drone_id | a.name                                             | a.attack_type                 | t.name        |
|:------------|-------------:|:---------------------------------------------------|:------------------------------|:--------------|
| SITE01      |            8 | Rogue Drone Intercepting ZKP Auth from IoT Sensors | Wireless – Drone Surveillance | Wi-Fi Sniffer |
| SITE01      |           16 | Rogue Drone Intercepting ZKP Auth from IoT Sensors | Wireless – Drone Surveillance | Wi-Fi Sniffer |
| SITE01      |           15 | Rogue Drone Intercepting ZKP Auth from IoT Sensors | Wireless – Drone Surveillance | Wi-Fi Sniffer |

</details>
<!-- EXAMPLE_QUERIES:END -->

## Versioning demo

Hypothesis: *"Wedel power station (coal, 260 MW) is destroyed"* (RPT-01), modelled as a branch.
TuringDB has no diff command, so the diff compares the cascade query's rows on main and on the branch.

<!-- VERSIONING_DEMO:START -->
**1. Replay the history** (`client.set_commit(<hash>)` on each commit of `CALL db.history()`):

| commit           |   nodes_added |   edges_added |   total_nodes |   reports |
|:-----------------|--------------:|--------------:|--------------:|----------:|
| 955916674038e186 |             0 |             0 |             0 |         0 |
| c785273b8fbf8d61 |        294179 |        845504 |        294179 |         0 |
| 15c17fe1415ecff3 |             7 |            17 |        294186 |         7 |
| 6471365fbb01cfd5 |             8 |            24 |        294194 |        15 |
| c3755c9413d384b5 |             6 |            16 |        294200 |        21 |

**2. Branch.** `client.new_change()` opened change `10`; inside it `MATCH (p:PowerPlant {gppd_idnr:'WRI1006130'}) DELETE p` then `COMMIT` (removes Wedel power station and its incident edges).

| | main | branch |
|---|--:|--:|
| nodes | 294,200 | 294,199 |
| edges | 845,561 | 845,550 |
| cascade rows | 47,823 | 44,496 |
| cascade latency (ms) | 112.6 | 88.8 |

**3. Diff of the cascade query, per site** (feeds = `POWERED_BY` plants, mw = their summed capacity):

| site   |   feeds_main |   mw_main |   cascade_rows_main |   feeds_branch |   mw_branch |   cascade_rows_branch |
|:-------|-------------:|----------:|--------------------:|---------------:|------------:|----------------------:|
| SITE01 |            3 |      36.5 |                6336 |              3 |        36.5 |                  6336 |
| SITE02 |            3 |      11   |                6720 |              3 |        11   |                  6720 |
| SITE03 |            3 |      26.3 |                4404 |              3 |        26.3 |                  4404 |
| SITE04 |            3 |     385   |                9981 |              2 |       125   |                  6654 |
| SITE05 |            3 |      64.1 |                7089 |              3 |        64.1 |                  7089 |
| SITE06 |            3 |     257   |               13293 |              3 |       257   |                 13293 |

Row diff: 3,327 rows exist only on main, 0 only on the branch. Every removed row runs through `WRI1006130`: ['WRI1006130'], all at ['SITE04'].

Reading: SITE04 keeps 40/40 of its class-A parts reachable through its remaining feeds, but its feed capacity drops from 385 MW to 125 MW. No other site changes.

**4. Discard.** `CHANGE DELETE` drops the branch; main still has 294,200 nodes / 845,561 edges.
<!-- VERSIONING_DEMO:END -->

## TuringDB 1.37 caveats found while building

| Area | Docs say | Observed |
|---|---|---|
| Install | README: `uv add turingdb` | installs 3.0, which cannot load the bundled graphs ("File outdated"); pin `turingdb==1.37` |
| Joins | shared variable across comma patterns = hash join | when the shared node is mid-path, e.g. `(s)<-[:DELIVERED_TO]-(po)-[:FOR_PART]->(pt), (po)-[:FROM_SUPPLIER]->(sup)`: every row returned **20x**, `count()` returns **no row**; with a 2+ hop second branch the query **never returns** (server at 140% CPU) |
| Server | `turingdb stop` stops the server | does not stop while a runaway query runs; needed `kill -9`. No query cancel or timeout |
| Procedures | `CALL db.procedures()` | parse error (`unexpected PROCEDURES`) |
| poledb doc | `-[r:KNOWS\|KNOWS_SN\|...]->` | `Not implemented: EdgeType \| EdgeType` |
| attack_scenarios doc | `OPTIONAL MATCH ... collect(...)` | `OPTIONAL MATCH not supported`, `Not implemented: COLLECT` |
| poledb doc | `Location` key = `address` | 987 duplicate addresses |
| Unknown types | - | naming a label or edge type that does not exist yet is an error, not 0 rows |
| Graph lifecycle | - | no `DROP GRAPH`: a rebuild stops the server, deletes `graphs/theatre`, restarts |
| Writes in a change | `COMMIT` needed between node and edge creates | also needed after `DELETE` before the change's own reads see it; `DELETE n` removes incident edges |
| Not supported (consistent with the skill docs) | | `DISTINCT`, `WITH`, `collect`, `sum`/`max`, grouped aggregates, `IN`, `STARTS WITH`/`CONTAINS`, string `<`/`>`, `count(DISTINCT)`, label `OR` in `WHERE`; `type` and `new` are reserved words (use backticks: ``cr.`type` ``); an alias may not reuse a variable name |

Branching (`new_change` / `checkout` / `CHANGE SUBMIT` / `CHANGE DELETE`), `COMMIT`, `CALL db.history()`
and time travel with `set_commit` behaved as documented.
