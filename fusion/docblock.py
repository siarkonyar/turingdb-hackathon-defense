"""Replace a generated block inside a Markdown file, delimited by
<!-- NAME:START --> ... <!-- NAME:END --> markers."""

from __future__ import annotations

from pathlib import Path


def splice_block(text: str, name: str, content: str) -> str:
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0 or j < i:
        raise ValueError(f"markers {start} / {end} not found (in order)")
    return f"{text[:i + len(start)]}\n{content.strip()}\n{text[j:]}"


def replace_block(path: Path, name: str, content: str) -> None:
    path.write_text(splice_block(path.read_text(encoding="utf-8"), name, content), encoding="utf-8")
