import pytest

from report_data import REPORTS
from reports import SOURCE_TYPES, Mention, Report, _lit, _validate, report_cypher


def _report(**kw) -> Report:
    base = dict(report_id="R1", batch=1, timestamp="2026-09-28T10:00:00Z", source_type="OSINT", confidence=0.5,
                latitude=53.0, longitude=-2.0, claim="struck", text="It's on fire",
                mentions=(Mention("Site", "site_id", "SITE01"),))
    return Report(**(base | kw))


def test_report_cypher_matches_assets_and_creates_edges():
    r = _report(mentions=(Mention("Site", "site_id", "SITE01"), Mention("PowerPlant", "gppd_idnr", "P1")),
                contradicts="R0", batch=2)
    q = report_cypher(r)
    assert q.startswith('MATCH (m0:Site {site_id: "SITE01"}), (m1:PowerPlant {gppd_idnr: "P1"}), '
                        '(o:Report {report_id: "R0"}) CREATE (r:Report {')
    assert q.count("[:MENTIONS") == 2 and "(r)-[:CONTRADICTS" in q
    assert "ts_epoch: 1790589600" in q and "synthetic: true" in q and 'text: "It\'s on fire"' in q


def test_literal_rejects_quotes_and_formats_scalars():
    assert _lit(True) == "true" and _lit(0.5) == "0.5" and _lit(3) == "3"
    with pytest.raises(ValueError):
        _lit('say "hi"')


@pytest.mark.parametrize("bad", [dict(source_type="RADIO"), dict(confidence=1.5), dict(mentions=())])
def test_report_validation(bad):
    with pytest.raises(ValueError):
        _report(**bad)


def test_contradiction_must_point_to_an_earlier_batch():
    with pytest.raises(ValueError):
        _validate((_report(report_id="A"), _report(report_id="B", contradicts="A")))
    with pytest.raises(ValueError):
        _validate((_report(report_id="A"), _report(report_id="A")))


def test_report_data_meets_the_brief():
    ids = {r.report_id for r in REPORTS}
    assert 18 <= len(REPORTS) <= 25
    assert {r.source_type for r in REPORTS} == SOURCE_TYPES
    assert len({r.batch for r in REPORTS}) in (2, 3)
    pairs = [(r.report_id, r.contradicts) for r in REPORTS if r.contradicts]
    assert len(pairs) >= 3 and all(c in ids for _, c in pairs)
    _validate(REPORTS)
    for r in REPORTS:
        report_cypher(r)  # every literal is safe to embed
