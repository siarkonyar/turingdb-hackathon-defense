"""Parsing of the `branch`, `a`/`b`, `types` and `bbox` query parameters.

A ref is `<branch>` or `<branch>@<commit>`: `main`, `main@313a10dec2245f64`, `4` (TuringDB change 4),
`4@ddbd8da13fb6ccd5`. Branch ids are `main` or a TuringDB change id (non-negative integer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAIN = "main"
_BRANCH = re.compile(r"^(main|\d{1,9})$")
_COMMIT = re.compile(r"^[0-9a-f]{4,40}$")


@dataclass(frozen=True)
class Ref:
    branch: str
    commit: str | None = None

    @property
    def is_main(self) -> bool:
        return self.branch == MAIN

    def __str__(self) -> str:
        return self.branch if self.commit is None else f"{self.branch}@{self.commit}"


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    def contains(self, lon: float | None, lat: float | None) -> bool:
        if lon is None or lat is None:
            return False
        crosses_antimeridian = self.west > self.east
        in_lon = (lon >= self.west or lon <= self.east) if crosses_antimeridian else self.west <= lon <= self.east
        return in_lon and self.south <= lat <= self.north


def parse_ref(raw: str | None) -> Ref:
    text = (raw or MAIN).strip()
    branch, _, commit = text.partition("@")
    if not _BRANCH.match(branch):
        raise ValueError(f"invalid branch {branch!r}: expected 'main' or a change id")
    if commit and not _COMMIT.match(commit):
        raise ValueError(f"invalid commit {commit!r}: expected a hex commit hash")
    return Ref(branch=branch, commit=commit or None)


def parse_bbox(raw: str | None) -> BBox | None:
    """`west,south,east,north` in degrees (the MapLibre getBounds() order)."""
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must be 'west,south,east,north'")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be numbers") from exc
    if not (-90 <= south <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("bbox out of range")
    return BBox(west, south, east, north)


def parse_kinds(raw: str | None, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not raw:
        return allowed
    kinds = tuple(dict.fromkeys(k.strip() for k in raw.split(",") if k.strip()))
    unknown = [k for k in kinds if k not in allowed]
    if unknown:
        raise ValueError(f"unknown types {unknown}; allowed: {list(allowed)}")
    return kinds
