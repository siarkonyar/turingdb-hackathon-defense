"""Resolve a plain-language question ("Hürmüz Boğazı kapanırsa ne olur?") to a cascade origin, without an LLM.

Deterministic on purpose: the demo must never depend on a model being warm. Turkish and English aliases cover
the 15 chokepoints; ports and facilities match on their distinctive name words. Ambiguity is returned to the
operator as candidates rather than guessed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from api.models import Node, OriginCandidate, OriginKind

CONFIDENT = 0.8
MARGIN = 0.15
MIN_TOKEN = 4
KIND_ORDER: dict[str, int] = {"chokepoint": 0, "port": 1, "facility": 2}
STOP = frozenset({"port", "of", "the", "strait", "straits", "canal", "sea", "co", "ltd", "inc", "jsc", "fze", "llc",
                  "gmbh", "sa", "ag", "plc", "corp", "group", "mining", "materials", "components", "trading",
                  "limani", "bogazi", "kanali"})

# normalized alias phrase -> canonical chokepoint name (as stored in the graph)
ALIASES: dict[str, str] = {
    "hormuz": "Strait of Hormuz", "hurmuz": "Strait of Hormuz",
    "taiwan": "Taiwan Strait", "tayvan": "Taiwan Strait",
    "malacca": "Strait of Malacca", "malakka": "Strait of Malacca", "malaka": "Strait of Malacca",
    "bab el mandeb": "Bab-el-Mandeb", "babulmendep": "Bab-el-Mandeb", "bab ul mendeb": "Bab-el-Mandeb",
    "bab el mendeb": "Bab-el-Mandeb", "kizildeniz": "Bab-el-Mandeb", "red sea": "Bab-el-Mandeb",
    "suez": "Suez Canal", "suveys": "Suez Canal",
    "panama": "Panama Canal",
    "gibraltar": "Strait of Gibraltar", "cebelitarik": "Strait of Gibraltar",
    "turkish straits": "Turkish Straits", "bosphorus": "Turkish Straits", "istanbul bogazi": "Turkish Straits",
    "turk bogazlari": "Turkish Straits", "canakkale": "Turkish Straits", "dardanelles": "Turkish Straits",
    "danish straits": "Danish Straits", "danimarka bogazlari": "Danish Straits",
    "dover": "Dover Strait", "mans": "Dover Strait",
    "korea strait": "Korea Strait", "kore bogazi": "Korea Strait",
    "luzon": "Luzon Strait", "sunda": "Sunda Strait", "lombok": "Lombok Strait", "florida": "Florida Strait",
}


def normalize(text: str) -> str:
    text = text.replace("ı", "i").replace("İ", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _has_phrase(haystack: str, phrase: str) -> bool:
    return f" {phrase} " in f" {haystack} "


def _tokens(name: str) -> set[str]:
    return {t for t in normalize(name).split() if t not in STOP and len(t) >= MIN_TOKEN}


def _score(q: str, words: set[str], node: Node, kind: OriginKind, aliased: set[str]) -> float:
    if node.name in aliased:
        return 1.0
    if _has_phrase(q, normalize(node.name)):
        return 0.95
    tokens = _tokens(node.name)
    found = tokens & words
    if not found:
        return 0.0
    if found == tokens:
        return 0.85 if kind != "facility" else 0.8
    return 0.5 if kind != "facility" else 0.3


def resolve(question: str, catalog: Sequence[tuple[Node, OriginKind]], limit: int = 8) -> list[OriginCandidate]:
    q = normalize(question)
    words = set(q.split())
    aliased = {name for phrase, name in ALIASES.items() if _has_phrase(q, phrase)}
    scored = [(_score(q, words, node, kind, aliased), node, kind) for node, kind in catalog]
    hits = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], KIND_ORDER[x[2]], x[1].name))
    return [OriginCandidate(node=node, origin_kind=kind, score=round(score, 3)) for score, node, kind in hits[:limit]]


def pick(candidates: Sequence[OriginCandidate]) -> OriginCandidate | None:
    """The single confident origin, or None when the operator should choose."""
    if not candidates or candidates[0].score < CONFIDENT:
        return None
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < MARGIN:
        return None
    return candidates[0]
