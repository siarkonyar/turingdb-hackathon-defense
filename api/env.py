"""Load a project `.env` file (gitignored) into the environment, without overriding real variables.

    OPSMAP_BACKEND=turingdb
    FEATHERLESS_API_KEY=...        # a secret: only ever read, never logged

Lines are KEY=VALUE; blank lines and `#` comments are ignored; one pair of surrounding quotes is stripped.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("opsmap.env")
ROOT = Path(__file__).resolve().parents[1]
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:  # trailing comment on an unquoted value
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_env(path: Path | None = None) -> list[str]:
    """Set variables from `.env` that the environment does not already define; returns their names."""
    path = path or Path(os.environ.get("OPSMAP_ENV_FILE", ROOT / ".env"))
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        return []
    values = parse_env(text)
    added = [k for k, v in values.items() if v and k not in os.environ]
    for key in added:
        os.environ[key] = values[key]
    return added
