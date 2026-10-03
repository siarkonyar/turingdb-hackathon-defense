"""Resolve a plain-language question ("What happens if the Strait of Hormuz closes?") to a cascade origin,
without an LLM.

Deterministic on purpose: the demo must never depend on a model being warm. Aliases cover
the 15 chokepoints; ports and facilities match on their distinctive name words. Ambiguity is returned to the
operator as candidates rather than guessed.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Sequence

from api.models import Node, OriginCandidate, OriginKind

CONFIDENT = 0.8
MARGIN = 0.15
MIN_TOKEN = 4
KIND_ORDER: dict[str, int] = {"chokepoint": 0, "port": 1, "country": 2, "company": 3, "facility": 4, "item": 5,
                              "plant": 6}
NAME_CACHE = 200_000  # the search catalog holds ~48k names; cached tokens keep a lookup well under a second
STOP = frozenset({"port", "of", "the", "strait", "straits", "canal", "sea", "co", "ltd", "inc", "jsc", "fze", "llc",
                  "gmbh", "sa", "ag", "plc", "corp", "group", "mining", "materials", "components", "trading",
                  # generic power-plant words: thousands of plant names share them
                  "power", "station", "plant", "solar", "wind", "hydro", "farm", "park", "scheme", "energy"})

# normalized alias phrase -> canonical chokepoint name (as stored in the graph)
ALIASES: dict[str, str] = {
    "hormuz": "Strait of Hormuz",
    "taiwan": "Taiwan Strait",
    "malacca": "Strait of Malacca",
    "bab el mandeb": "Bab-el-Mandeb", "red sea": "Bab-el-Mandeb",
    "suez": "Suez Canal",
    "panama": "Panama Canal",
    "gibraltar": "Strait of Gibraltar",
    "turkish straits": "Turkish Straits", "bosphorus": "Turkish Straits", "dardanelles": "Turkish Straits",
    "danish straits": "Danish Straits",
    "dover": "Dover Strait", "english channel": "Dover Strait",
    "korea strait": "Korea Strait",
    "luzon": "Luzon Strait", "sunda": "Sunda Strait", "lombok": "Lombok Strait", "florida": "Florida Strait",
}


@lru_cache(maxsize=NAME_CACHE)
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _has_phrase(haystack: str, phrase: str) -> bool:
    return f" {phrase} " in f" {haystack} "


@lru_cache(maxsize=NAME_CACHE)
def _tokens(name: str) -> frozenset[str]:
    return frozenset({t for t in normalize(name).split() if t not in STOP and len(t) >= MIN_TOKEN})


def _score(q: str, words: set[str], node: Node, kind: OriginKind, aliased: set[str]) -> float:
    if node.name in aliased:
        return 1.0
    name = normalize(node.name)
    if len(name) >= MIN_TOKEN and _has_phrase(q, name):
        return 0.95
    tokens = _tokens(node.name)
    found = tokens & words
    if not found:
        return 0.0
    if kind == "plant":  # ~35k plant names share common words: only the full name (above) is confident
        return 0.6 if found == tokens else 0.3
    if found == tokens:
        return 0.85 if kind != "facility" else 0.8
    return 0.5 if kind != "facility" else 0.3


def resolve(question: str, catalog: Sequence[tuple[Node, OriginKind]], limit: int = 8) -> list[OriginCandidate]:
    q = normalize(question)
    words = set(q.split())
    aliased = {name for phrase, name in ALIASES.items() if _has_phrase(q, phrase)}
    scored = [(_score(q, words, node, kind, aliased), node, kind) for node, kind in catalog]
    hits = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], KIND_ORDER.get(x[2], 9), x[1].name))
    return [OriginCandidate(node=node, origin_kind=kind, score=round(score, 3)) for score, node, kind in hits[:limit]]


def pick(candidates: Sequence[OriginCandidate]) -> OriginCandidate | None:
    """The single confident origin, or None when the operator should choose."""
    if not candidates or candidates[0].score < CONFIDENT:
        return None
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < MARGIN:
        return None
    return candidates[0]
