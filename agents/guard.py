"""Static checks on agent-written Cypher before it reaches TuringDB 1.37.

1.37 has no query cancel or timeout, and some shapes never return (comma-joined patterns sharing a
variable mid-path, see docs/theatre.md). Agents may only read, with one linear MATCH path, and every
result is capped. Rejections explain the rule so the model can rewrite the query.
"""

from __future__ import annotations

import re

MAX_LIMIT = 300
DEFAULT_LIMIT = 100
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_WORD = re.compile(r"[A-Za-z_]+")
FORBIDDEN = {
    "CREATE", "DELETE", "DETACH", "SET", "REMOVE", "MERGE", "DROP", "CHANGE", "COMMIT", "LOAD", "SUBMIT",
    "INDEX", "MERGE_DATAPARTS", "FOREACH",
}
UNSUPPORTED = {
    "OPTIONAL": "OPTIONAL MATCH is not supported by TuringDB 1.37",
    "WITH": "WITH is not supported by TuringDB 1.37; return the columns and aggregate in the answer",
    "UNWIND": "UNWIND is not supported by TuringDB 1.37",
    "UNION": "UNION is not supported; run two queries",
    "DISTINCT": "DISTINCT is not supported by TuringDB 1.37",
    "COLLECT": "collect() is not supported by TuringDB 1.37",
    "CONTAINS": "CONTAINS is not supported by TuringDB 1.37; compare with = or use numeric ranges",
    "STARTS": "STARTS WITH is not supported by TuringDB 1.37",
    "IN": "IN lists are not supported by TuringDB 1.37; use (x = a OR x = b)",
}
ALLOWED_CALLS = ("CALL db.labels()", "CALL db.edgeTypes()", "CALL db.propertyTypes()")


class UnsafeQuery(ValueError):
    pass


def _mask_strings(cypher: str) -> str:
    return _STRING.sub(lambda m: "'" + "_" * (len(m.group(0)) - 2) + "'", cypher)


def _top_level_commas(segment: str) -> bool:
    depth = 0
    for ch in segment:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
    return False


def check_read_query(cypher: str) -> str:
    """Return the query to run (LIMIT enforced) or raise UnsafeQuery."""
    text = " ".join(cypher.strip().rstrip(";").split())
    if not text:
        raise UnsafeQuery("empty query")
    if text in ALLOWED_CALLS:
        return text
    masked = _mask_strings(text)
    if ";" in masked:
        raise UnsafeQuery("one statement per query")
    words = [w.upper() for w in _WORD.findall(masked)]
    bad = sorted(FORBIDDEN & set(words))
    if bad:
        raise UnsafeQuery(f"read-only access: {', '.join(bad)} is not allowed here; the branch tools perform writes")
    for word, why in UNSUPPORTED.items():
        if word in words:
            raise UnsafeQuery(why)
    if "CALL" in words:
        raise UnsafeQuery(f"only {', '.join(ALLOWED_CALLS)} may be called")
    if not masked.upper().startswith("MATCH "):
        raise UnsafeQuery("start with MATCH")
    if words.count("MATCH") != 1:
        raise UnsafeQuery("use a single MATCH clause")
    upper = masked.upper()
    ret = upper.find(" RETURN ")
    if ret < 0:
        raise UnsafeQuery("add a RETURN clause")
    where = upper.find(" WHERE ")
    pattern = masked[len("MATCH "):where if 0 <= where < ret else ret]
    if _top_level_commas(pattern):
        raise UnsafeQuery("use ONE linear path pattern, e.g. (a)-[:R]->(b)<-[:S]-(c); comma-separated patterns "
                          "hang TuringDB 1.37")
    if re.search(r"\[[^\]]*\*", pattern):
        raise UnsafeQuery("variable-length relationships ([*..]) are not allowed; spell out the hops")
    limit = re.search(r"\bLIMIT\s+(\d+)\s*$", upper)
    if limit:
        if int(limit.group(1)) > MAX_LIMIT:
            text = text[:limit.start(1)] + str(MAX_LIMIT)
        return text
    if re.search(r"\bLIMIT\b", upper):
        raise UnsafeQuery("LIMIT must be the last clause")
    aggregate_only = re.fullmatch(r".* RETURN\s+(COUNT\([^)]*\)( AS \w+)?\s*,?\s*)+", upper) is not None
    return text if aggregate_only else f"{text} LIMIT {DEFAULT_LIMIT}"
