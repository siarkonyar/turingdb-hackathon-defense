"""Reads an operator's what-if question and names the graph entities it is about.

Used by /cascade/ask only when the deterministic resolver finds no confident match ("What if Europe's biggest
port shuts?", misspellings, indirect descriptions). The model never queries the graph or estimates impact: it
turns free text into concrete English entity names plus a kind hint, and the resolver then looks those names up
in the TuringDB catalog. One bounded call (no retries), so a slow or missing model only costs the fallback message.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agents.config import load_agent_settings
from agents.llm import FeatherlessLLM, LLMError, _balanced_objects, strip_reasoning

log = logging.getLogger("agents.place_extractor")

EXTRACT_TIMEOUT_S = 60.0  # a cold Featherless model can take ~60 s on its first call
MAX_TARGETS = 3
MAX_NAME_LEN = 120
KINDS = ("chokepoint", "port", "facility", "company", "country", "power_plant", "item", "other")

SYSTEM_PROMPT = f"""You read a defence-logistics what-if question and name the real-world things it asks about.
The supply-chain graph contains: sea chokepoints (e.g. Strait of Hormuz, Suez Canal), sea ports (e.g. Port of
Rotterdam, Port of Busan), industrial facilities (named after their company and city), companies, countries,
power plants, and supply items (minerals, materials, components, e.g. Cobalt ore, Rare earth ore).

Reply with ONE JSON object and nothing else:
{{"targets": [{{"name": "<concrete English name as it would appear in a database>", "kind": "<one of {', '.join(KINDS)}>"}}]}}

Rules:
- Use English names and resolve descriptions to a concrete name ("Europe's biggest port" -> "Port of Rotterdam",
  "the Red Sea route" -> "Bab-el-Mandeb", "Hormoz" -> "Strait of Hormuz").
- Prefer the most specific thing that is lost, closed or destroyed in the question. At most {MAX_TARGETS} targets,
  most important first.
- If the question names nothing that could be in such a graph, reply {{"targets": []}}."""


@dataclass(frozen=True)
class Mention:
    name: str
    kind: str  # one of KINDS


class PlaceExtractor:
    """Callable: question -> mentions. Raises LLMError when the model is unavailable or the reply is unusable."""

    def __init__(self, llm: FeatherlessLLM) -> None:
        self._llm = llm

    @staticmethod
    def from_env() -> PlaceExtractor:
        return PlaceExtractor(FeatherlessLLM(load_agent_settings(), timeout_s=EXTRACT_TIMEOUT_S))

    def __call__(self, question: str) -> list[Mention]:
        reply = self._llm.chat([{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": question}],
                               agent="place_extractor", temperature=0.0, max_tokens=300, bounded=True)
        mentions = parse_mentions(reply)
        log.info("place extractor %r -> %s", question, [m.name for m in mentions])
        return mentions


def parse_mentions(reply: str) -> list[Mention]:
    for obj in _balanced_objects(strip_reasoning(reply)):
        try:
            data = json.loads(obj)
        except json.JSONDecodeError:
            continue
        targets = data.get("targets") if isinstance(data, dict) else None
        if not isinstance(targets, list):
            continue
        out: list[Mention] = []
        for t in targets[:MAX_TARGETS]:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name", "")).strip()[:MAX_NAME_LEN]
            kind = str(t.get("kind", "other"))
            if name:
                out.append(Mention(name=name, kind=kind if kind in KINDS else "other"))
        return out
    raise LLMError("place extractor reply had no targets object")
