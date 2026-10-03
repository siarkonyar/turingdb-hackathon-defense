"""Question -> cascade origin. Deterministic, no LLM: an alias table plus name-token matching."""

from __future__ import annotations

from api.cascade_resolve import normalize, pick, resolve
from api.nodes import make_node

CATALOG = [
    (make_node(1, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4}), "chokepoint"),
    (make_node(2, "Chokepoint", {"name": "Taiwan Strait", "latitude": 24.0, "longitude": 119.5}), "chokepoint"),
    (make_node(3, "Chokepoint", {"name": "Bab-el-Mandeb", "latitude": 12.6, "longitude": 43.3}), "chokepoint"),
    (make_node(4, "Port", {"name": "Port of Busan", "latitude": 35.1, "longitude": 129.0}), "port"),
    (make_node(5, "Port", {"name": "Port of Hamburg", "latitude": 53.5, "longitude": 9.9}), "port"),
    (make_node(6, "Port", {"name": "Port of Bandar Abbas", "latitude": 27.1, "longitude": 56.2}), "port"),
    (make_node(7, "Facility", {"name": "Meridian Mining FZE - Dubai", "latitude": 25.2, "longitude": 55.3}), "facility"),
]


def names(cands):
    return [c.node.name for c in cands]


def test_normalize_strips_turkish_diacritics_and_punctuation():
    assert normalize("Hürmüz Boğazı kapanırsa NE olur?") == "hurmuz bogazi kapanirsa ne olur"
    assert normalize("Bab-el-Mandeb") == "bab el mandeb"


def test_turkish_alias_resolves_hormuz_confidently():
    cands = resolve("Hürmüz Boğazı çöktü, ne olacak şimdi?", CATALOG)
    assert names(cands)[0] == "Strait of Hormuz" and cands[0].score == 1.0
    assert pick(cands).node.name == "Strait of Hormuz"


def test_english_full_name_and_short_name():
    assert pick(resolve("What if the Strait of Hormuz closes?", CATALOG)).node.name == "Strait of Hormuz"
    assert pick(resolve("taiwan blockade", CATALOG)).node.name == "Taiwan Strait"
    assert pick(resolve("Kızıldeniz kapanırsa", CATALOG)).node.name == "Bab-el-Mandeb"


def test_port_by_city_word():
    assert pick(resolve("Busan limanı kapanırsa", CATALOG)).node.name == "Port of Busan"


def test_facility_by_name_tokens():
    assert pick(resolve("Meridian Dubai goes down", CATALOG)).node.name == "Meridian Mining FZE - Dubai"


def test_pick_requires_margin():
    cands = resolve("Busan and Hamburg ports close", CATALOG)
    assert {"Port of Busan", "Port of Hamburg"} <= set(names(cands))
    assert pick(cands) is None


def test_unknown_place_gives_no_candidates():
    assert resolve("what happens tomorrow?", CATALOG) == []
    assert pick([]) is None


def test_stop_words_alone_do_not_match():
    assert resolve("the port of the strait", CATALOG) == []


def test_limit_and_kind_priority():
    cands = resolve("bandar abbas hormuz", CATALOG, limit=2)
    assert len(cands) == 2 and cands[0].origin_kind == "chokepoint"
