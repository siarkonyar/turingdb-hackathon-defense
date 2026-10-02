"""Cross-domain example queries over `theatre`: run each, record rows + latency, and write the
results table into docs/theatre.md.

    uv run python fusion/theatre_queries.py
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import REPO_ROOT  # noqa: E402
from docblock import replace_block  # noqa: E402
from tdb import connect, timed_query, use_theatre  # noqa: E402

WARM_RUNS = 5
DOC = REPO_ROOT / "docs" / "theatre.md"


@dataclass(frozen=True)
class Example:
    qid: str
    title: str
    datasets: tuple[str, ...]
    cypher: str


EXAMPLES: tuple[Example, ...] = (
    Example("Q1", "Energy -> supply cascade (8 hops): Wedel power station -> SITE04 -> recent POs -> class-A "
                  "parts -> their primary suppliers -> logistics suppliers -> high-risk shipments",
            ("power_plants", "supply_chain", "logistics_risk"),
            """MATCH (pp:PowerPlant {gppd_idnr:'WRI1006130'})<-[:POWERED_BY]-(s:Site)<-[:DELIVERED_TO]-(po:PurchaseOrder)-[:FOR_PART]->(pt:Part)-[:SUPPLIED_BY]->(sup:Supplier)-[:SOURCES_FROM]->(ls:Supplier)<-[:FROM_SUPPLIER]-(sh:Shipment)-[:CLASSIFIED_AS]->(rc:RiskClassification {name:'High Risk'})
WHERE pt.criticality_class = 'A' AND po.ts_epoch >= 1719792000
RETURN pp.name, s.site_id, po.po_id, pt.part_id, sup.supplier_id, ls.supplier_id, sh.shipment_id, sh.delay_probability"""),
    Example("Q2", "Cyber kill chain to a physical asset: ICS attacks and MITRE techniques against the plants "
                  "powering SITE01",
            ("supply_chain", "power_plants", "attack_scenarios"),
            """MATCH (s:Site {site_id:'SITE01'})-[:POWERED_BY]->(pp:PowerPlant)-[:RUNS]->(at:AssetType {asset_type_id:'ICS_SCADA'})<-[:TARGETS]-(a:Attack)-[:USES_TECHNIQUE]->(t:MitreTechnique)
RETURN pp.name, a.name, a.attack_type, t.code, t.name"""),
    Example("Q3", "Sabotage leads: criminal damage and arson within 1 km of the plants feeding SITE01",
            ("supply_chain", "power_plants", "poledb"),
            """MATCH (s:Site {site_id:'SITE01'})-[:POWERED_BY]->(pp:PowerPlant)<-[n:NEAR]-(l:Location)<-[:OCCURRED_AT]-(cr:Crime)
WHERE cr.`type` = 'Criminal damage and arson' AND n.distance_km < 1.0
RETURN pp.name, l.address, n.distance_km, cr.timestamp, cr.last_outcome"""),
    Example("Q4", "Insider leads: residents near a site that depends on Salford Refuse Treatment Plant whose "
                  "known associates are party to crimes",
            ("power_plants", "supply_chain", "poledb"),
            """MATCH (pp:PowerPlant {gppd_idnr:'GBR0000912'})<-[:POWERED_BY]-(s:Site)<-[n:NEAR]-(l:Location)<-[:CURRENT_ADDRESS]-(p:Person)-[:KNOWS]-(a:Person)-[:PARTY_TO]->(cr:Crime)
RETURN s.site_id, p.name, p.surname, l.address, n.distance_km, a.name, a.surname, cr.`type`, cr.timestamp"""),
    Example("Q5", "Gas-fired dependency: part suppliers powered by gas plants whose logistics partners show "
                  "delay probability > 0.9",
            ("power_plants", "supply_chain", "logistics_risk"),
            """MATCH (f:Fuel {name:'Gas'})<-[:PRIMARY_FUEL]-(pp:PowerPlant)<-[:POWERED_BY]-(sup:Supplier)-[:SOURCES_FROM]->(ls:Supplier)<-[:FROM_SUPPLIER]-(sh:Shipment)
WHERE sh.delay_probability > 0.9
RETURN sup.supplier_id, sup.place, sup.country_code, pp.name, pp.capacity_mw, ls.supplier_id, sh.shipment_id, sh.delay_probability"""),
    Example("Q6", "ISR cross-check: collision-warning readings of drones named in drone reports about a site, "
                  "and the plants that power that site",
            ("drone_swarm", "supply_chain", "power_plants"),
            """MATCH (rd:Reading)-[:OF_DRONE]->(d:Drone)<-[:MENTIONS]-(r:Report)-[:MENTIONS]->(s:Site)-[:POWERED_BY]->(pp:PowerPlant)
WHERE r.source_type = 'drone' AND rd.collision_warning = 1
RETURN r.report_id, r.claim, d.drone_id, rd.timestamp, rd.latitude, rd.longitude, s.site_id, pp.name"""),
    Example("Q7", "Hypothesis board: contradicting report pairs about power plants and every Site or Supplier "
                  "that depends on the disputed plant",
            ("power_plants", "supply_chain", "intel"),
            """MATCH (later:Report)-[:CONTRADICTS]->(earlier:Report)-[:MENTIONS]->(pp:PowerPlant)<-[e:POWERED_BY]-(x)
RETURN earlier.report_id, earlier.claim, earlier.confidence, later.report_id, later.claim, later.confidence, pp.name, labels(x), x.name, e.distance_km"""),
    Example("Q8", "Counter-UAS: attack scenarios (and their tools) that target the avionics of the ISR swarm "
                  "patrolling SITE01",
            ("attack_scenarios", "drone_swarm", "supply_chain"),
            """MATCH (t:Tool)<-[:USES_TOOL]-(a:Attack)-[:TARGETS]->(at:AssetType {asset_type_id:'UAS_AVIONICS'})<-[:RUNS]-(d:Drone)-[:PATROLS]->(s:Site)
RETURN s.site_id, d.drone_id, a.name, a.attack_type, t.name"""),
)


@dataclass(frozen=True)
class Measured:
    example: Example
    rows: int
    cold_ms: float
    warm_ms: float
    sample: str


def measure(client, ex: Example) -> Measured:
    first = timed_query(client, ex.cypher)
    warm = [timed_query(client, ex.cypher).server_ms for _ in range(WARM_RUNS)]
    sample = first.frame.head(3).to_markdown(index=False) if len(first.frame) else "_no rows_"
    return Measured(ex, len(first.frame), first.server_ms, statistics.median(warm), sample)


def results_markdown(results: list[Measured]) -> str:
    lines = [f"Generated by `fusion/theatre_queries.py` against the current `theatre` HEAD with `turingdb` 1.37. "
             f"Latency is server-side execution time (`client.get_query_exec_time()`): first run, and the median "
             f"of {WARM_RUNS} warm runs.", "",
             "| Query | Question | Source datasets crossed | Rows | First run (ms) | Warm median (ms) |",
             "|---|---|---|--:|--:|--:|"]
    lines += [f"| {m.example.qid} | {m.example.title.split(':')[0]} | {', '.join(m.example.datasets)} | "
              f"{m.rows:,} | {m.cold_ms:.1f} | {m.warm_ms:.1f} |" for m in results]
    for m in results:
        lines += ["", f"### {m.example.qid}. {m.example.title}", "",
                  f"Crosses: {', '.join(f'`{d}`' for d in m.example.datasets)}. "
                  f"{m.rows:,} rows, {m.warm_ms:.1f} ms warm.", "",
                  "```cypher", m.example.cypher, "```", "",
                  "<details><summary>First 3 rows</summary>", "", m.sample, "", "</details>"]
    return "\n".join(lines)


def main() -> None:
    client = connect()
    use_theatre(client)
    results = []
    for ex in EXAMPLES:
        m = measure(client, ex)
        print(f"{ex.qid}: {m.rows:>6,} rows  first {m.cold_ms:6.1f} ms  warm median {m.warm_ms:6.1f} ms  "
              f"[{', '.join(ex.datasets)}]")
        results.append(m)
    replace_block(DOC, "EXAMPLE_QUERIES", results_markdown(results))
    print(f"[doc] updated EXAMPLE_QUERIES block in {DOC.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
