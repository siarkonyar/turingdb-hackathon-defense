# Global Power Plant Database - TuringDB Graph

A graph view of the **Global Power Plant Database** (WRI, v1.3.0): ~34,900 power plants
worldwide with location, capacity, primary/secondary fuels, owner, and reported/estimated
generation, plus `NEAR` edges linking every pair of plants within 10 km of each other.

- **Graph name:** `power_plants`  ·  **Store:** [`graphs/power_plants/`](../graphs/power_plants)

## Schema

### Nodes (45,262)

| Label | Count | Key | Properties |
|---|---|---|---|
| `PowerPlant` | 34,936 | `gppd_idnr` | `name`, `gppd_idnr`, `capacity_mw`, `latitude`, `longitude`, `primary_fuel`, `commissioning_year`, `owner`, `source`, `country_code`, `generation_gwh_2019`, `year_of_capacity_data` |
| `Country` | 167 | `country_code` (ISO3) | `name` (full country name), `country_code` |
| `Fuel` | 15 | fuel name | `name` (Solar, Hydro, Wind, Gas, Coal, Oil, Biomass, Waste, Nuclear, Geothermal, Storage, Other, Cogeneration, Petcoke, Wave and Tidal) |
| `Owner` | 10,144 | owner name | `name` |

**Every node has a `name` property.** For `PowerPlant` it is the plant name from the
dataset (falling back to `PowerPlant: <gppd_idnr>` if blank); for the other labels it is the
human-readable country / fuel / owner name.

### Edges (149,218)

| Edge | From → To | Count | Meaning |
|---|---|---|---|
| `LOCATED_IN` | `PowerPlant` → `Country` | 34,936 | Plant's country |
| `PRIMARY_FUEL` | `PowerPlant` → `Fuel` | 34,936 | Plant's main fuel |
| `ALSO_USES` | `PowerPlant` → `Fuel` | 2,312 | Secondary fuels (`other_fuel1/2/3`) |
| `OWNED_BY` | `PowerPlant` → `Owner` | 20,868 | Plant's owner (where known) |
| `NEAR` | `PowerPlant` → `PowerPlant` | 56,166 | Plants within 10 km of each other (great-circle distance) |

`NEAR` edges carry a `distance_km` property (Double, 3 decimals). Each pair is stored once, so
match them **undirected**: `(p)-[e:NEAR]-(q)`. Co-located units (e.g. a dam and its pumped-storage
plant) have `distance_km = 0.0`. 24,001 plants have at least one neighbour; the densest cluster
has 57. `NEAR` was added as its own commit on top of the original import (visible in `CALL db.history()`).

### Shape

```
(Country) <--LOCATED_IN-- (PowerPlant) --PRIMARY_FUEL--> (Fuel)
                              |    \--ALSO_USES----------> (Fuel)
                              |--OWNED_BY--> (Owner)
                              \--NEAR {distance_km}-- (PowerPlant)
```

## What it enables

- **Energy-security mapping** - generation capacity by country and fuel; fuel-mix and
  import/fuel-dependency profiles per country.
- **Ownership concentration** - which owners control the most capacity, and where.
- **Critical-infrastructure geolocation** - every plant carries lat/long for spatial joins.
- **Co-location / collateral exposure** - `NEAR` answers "what else sits within 10 km of this
  site?", finds plants that cross a border, and shows clusters where one strike, flood, or
  wildfire hits several plants at once.

## Quick start

```bash
# from the repo root
turingdb start -turing-dir "$(pwd)" -ui -ui-port 8080
```

```python
from turingdb import TuringDB
c = TuringDB("json", host="http://localhost:6666")
c.load_graph("power_plants"); c.set_graph("power_plants")

# plants in a country with fuel and capacity
c.query("""
  MATCH (p:PowerPlant)-[:LOCATED_IN]->(co:Country {country_code:'USA'}),
        (p)-[:PRIMARY_FUEL]->(f:Fuel)
  RETURN p.name, f.name, p.capacity_mw LIMIT 20
""")

# all plants for one owner
c.query("MATCH (p:PowerPlant)-[:OWNED_BY]->(o:Owner) WHERE o.name = 'EDF' RETURN p.name, p.capacity_mw")

# everything within 10 km of a nuclear plant, with distance and country
c.query("""
  MATCH (p:PowerPlant {name:'Kernkraftwerk Beznau'})-[e:NEAR]-(q:PowerPlant)-[:LOCATED_IN]->(co:Country)
  RETURN q.name, q.primary_fuel, co.name, e.distance_km
""")

# nearby plant pairs that cross a national border
c.query("""
  MATCH (p:PowerPlant)-[:LOCATED_IN]->(a:Country),
        (p)-[e:NEAR]-(q:PowerPlant)-[:LOCATED_IN]->(b:Country)
  WHERE a.country_code <> b.country_code
  RETURN p.name, a.name, q.name, b.name, e.distance_km LIMIT 20
""")

# tighter radius: filter on the edge property
c.query("MATCH (p:PowerPlant)-[e:NEAR]-(q:PowerPlant) WHERE e.distance_km < 2.0 AND p.country_code = 'UKR' RETURN p.name, q.name, e.distance_km")
```

## License

Source data: Global Power Plant Database, World Resources Institute -
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Retain attribution to WRI.
