"""Intelligence layer: commit hand-written synthetic Report nodes in batches (one TuringDB
commit per batch) so the operating picture has a history to replay and diff."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from turingdb import TuringDB

from tdb import count

SOURCE_TYPES = frozenset({"drone", "OSINT", "HUMINT", "SIGINT"})
EDGE_PROPS = "{synthetic: true, source: 'theatre'}"


@dataclass(frozen=True)
class Mention:
    label: str
    key: str
    value: str


@dataclass(frozen=True)
class Report:
    report_id: str
    batch: int
    timestamp: str  # ISO-8601 UTC
    source_type: str
    confidence: float
    latitude: float
    longitude: float
    claim: str  # short machine-readable claim, e.g. "destroyed" / "operational"
    text: str
    mentions: tuple[Mention, ...]
    contradicts: str | None = None  # report_id of an earlier report this one disputes

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"{self.report_id}: bad source_type {self.source_type}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"{self.report_id}: confidence out of range")
        if not self.mentions:
            raise ValueError(f"{self.report_id}: a report must mention at least one asset")


def _lit(value: str | float | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if '"' in value or "\\" in value:
        raise ValueError(f"string literal may not contain quotes/backslashes: {value[:40]}")
    return f'"{value}"'


def _epoch(iso: str) -> int:
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def report_cypher(r: Report) -> str:
    """One self-contained statement: MATCH every mentioned asset, CREATE the report and its edges."""
    props = {"report_id": r.report_id, "name": f"Report: {r.report_id}", "text": r.text,
             "timestamp": r.timestamp, "ts_epoch": _epoch(r.timestamp), "source_type": r.source_type,
             "confidence": r.confidence, "latitude": r.latitude, "longitude": r.longitude, "claim": r.claim,
             "batch": r.batch, "source": "intel", "synthetic": True}
    prop_str = ", ".join(f"{k}: {_lit(v)}" for k, v in props.items())
    matches = [f"(m{i}:{m.label} {{{m.key}: {_lit(m.value)}}})" for i, m in enumerate(r.mentions)]
    creates = [f"(r:Report {{{prop_str}}})"]
    creates += [f"(r)-[:MENTIONS {EDGE_PROPS}]->(m{i})" for i in range(len(r.mentions))]
    if r.contradicts:
        matches.append(f"(o:Report {{report_id: {_lit(r.contradicts)}}})")
        creates.append(f"(r)-[:CONTRADICTS {EDGE_PROPS}]->(o)")
    return f"MATCH {', '.join(matches)} CREATE {', '.join(creates)}"


def _validate(reports: tuple[Report, ...]) -> None:
    ids = Counter(r.report_id for r in reports)
    dupes = [i for i, n in ids.items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate report ids {dupes}")
    batch_of = {r.report_id: r.batch for r in reports}
    for r in reports:
        if r.contradicts and batch_of.get(r.contradicts, r.batch) >= r.batch:
            raise ValueError(f"{r.report_id} must contradict a report from an earlier batch")


def commit_report_batches(client: TuringDB, reports: tuple[Report, ...] | None = None) -> None:
    if reports is None:
        from report_data import REPORTS
        reports = REPORTS
    _validate(reports)
    for batch in sorted({r.batch for r in reports}):
        group = [r for r in reports if r.batch == batch]
        change = client.new_change()
        client.checkout(change=change)
        for r in group:
            client.query(report_cypher(r))
        client.query("CHANGE SUBMIT")
        client.checkout()
        _verify_batch(client, reports, batch)


def _verify_batch(client: TuringDB, reports: tuple[Report, ...], batch: int) -> None:
    done = [r for r in reports if r.batch <= batch]
    want = (len(done), sum(len(r.mentions) for r in done), sum(1 for r in done if r.contradicts))
    # TuringDB rejects queries naming an edge type that does not exist yet, rather than returning 0 rows.
    edge_types = set(client.query("CALL db.edgeTypes()")["edgeType"])
    got = (count(client, "MATCH (r:Report) RETURN count(r)"),
           count(client, "MATCH (r:Report)-[e:MENTIONS]->(x) RETURN count(e)"),
           count(client, "MATCH (r:Report)-[e:CONTRADICTS]->(o:Report) RETURN count(e)")
           if "CONTRADICTS" in edge_types else 0)
    if got != want:
        raise RuntimeError(f"report batch {batch}: (reports, mentions, contradicts) = {got}, expected {want}; "
                           "a mentioned asset key probably matched zero or several nodes")
    print(f"[intel] batch {batch} committed: {got[0]} reports, {got[1]} MENTIONS, {got[2]} CONTRADICTS so far")
