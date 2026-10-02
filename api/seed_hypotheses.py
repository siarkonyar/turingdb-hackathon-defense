"""Seed the live `theatre` graph with competing intelligence hypotheses, one TuringDB change each.

    uv run python -m api.seed_hypotheses            # create the branches (skips names already present)
    uv run python -m api.seed_hypotheses --reset    # delete existing hypothesis branches first

Each hypothesis is grounded in a CONTRADICTS pair of Report nodes (docs/theatre.md, Q7). A branch holds a
(:Hypothesis {name, confidence, description}) marker; plants it claims are destroyed are deleted with their
cascade statuses, plants it claims are degraded get ops_status 'at_risk'. Changes are not submitted, so
main is never modified; with an `-in-memory` server they vanish on restart, so run this after starting it.
"""

from __future__ import annotations

import argparse

from api.backends.turing import TuringBackend
from api.config import load_settings
from api.refs import Ref
from api.support import Stopwatch

# (name, confidence, description, plants lost, plants at risk); plants by gppd_idnr
HYPOTHESES = (
    ("H1 · Wedel destroyed", 0.35,
     "Kinetic strike destroyed Wedel power station (RPT-01); SITE04 Hamburg-Finkenwerder loses its largest feed. "
     "Contradicted by grid telemetry (RPT-08) and imagery (RPT-19).",
     ("WRI1006130",), ()),
    ("H2 · Wedel degraded, operational", 0.65,
     "Wedel coal units still exporting (RPT-08) with scorch damage at the switchyard (RPT-19): degraded, not lost. "
     "SITE04 keeps power but its feed is at risk.",
     (), ("WRI1006130", "WRI1006131")),
    ("H3 · EC Rzeszów sabotaged", 0.40,
     "Unplanned gas-turbine trip after hostile chatter (RPT-04, RPT-17) is sabotage; SITE06 Rzeszów-Jasionka "
     "loses its feed. Contradicted by the grid operator's scheduled-test statement (RPT-18).",
     ("WRI1019087",), ()),
)


def plant_ids(backend: TuringBackend, gppd: tuple[str, ...]) -> list[str]:
    if not gppd:
        return []
    s = backend._session(Ref("main"), Stopwatch("turingdb"))
    ids = []
    for code in gppd:
        frame = s.q(f"MATCH (p:PowerPlant) WHERE p.gppd_idnr = '{code}' RETURN p")
        if frame.empty:
            raise SystemExit(f"plant {code} not in graph {backend.graph}")
        ids.append(str(frame["p"].iloc[0]))
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete existing hypothesis branches first")
    args = parser.parse_args()
    settings = load_settings()
    backend = TuringBackend(settings.turingdb_host, settings.turingdb_graph)

    existing = {b.label: b.id for b in backend.branches().branches if b.kind == "hypothesis"}
    if args.reset:
        for label, change in existing.items():
            backend._open(Ref(change), Stopwatch("turingdb")).q("CHANGE DELETE")
            print(f"deleted {label} (change {change})")
        existing = {}
    for name, confidence, description, lost, at_risk in HYPOTHESES:
        if name in existing:
            print(f"exists  {name} (change {existing[name]})")
            continue
        change = backend.create_hypothesis(name, confidence, description,
                                           lost=plant_ids(backend, lost), at_risk=plant_ids(backend, at_risk))
        print(f"created {name} (change {change}, confidence {confidence:.2f})")


if __name__ == "__main__":
    main()
