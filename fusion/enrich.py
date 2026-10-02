"""Derived (non-invented) enrichment: ISO timestamps for events and coordinates inherited
from linked Location nodes or aggregated from members."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _stamp(dt: datetime) -> dict[str, object]:
    return {"timestamp": dt.strftime(ISO_FMT), "ts_epoch": int(dt.timestamp())}


def ts_from_ymd(value: str | None) -> dict[str, object]:
    """'2024-12-16' -> {'timestamp': '2024-12-16T00:00:00Z', 'ts_epoch': ...}; {} when missing/invalid."""
    if not isinstance(value, str) or not value:
        return {}
    try:
        return _stamp(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc))
    except ValueError:
        return {}


def ts_from_dmy(date: str | None, time: str | None = None) -> dict[str, object]:
    """poledb style '21/08/2017' (+ optional '20:32')."""
    if not isinstance(date, str) or not date:
        return {}
    try:
        dt = datetime.strptime(date, "%d/%m/%Y")
        if isinstance(time, str) and time:
            hh, mm = time.split(":")[:2]
            dt = dt.replace(hour=int(hh), minute=int(mm))
        return _stamp(dt.replace(tzinfo=timezone.utc))
    except ValueError:
        return {}


def ts_from_step(step: int, start: datetime, step_seconds: int) -> dict[str, object]:
    return _stamp(start + timedelta(seconds=int(step) * step_seconds))


def inherit_coords(edges: pd.DataFrame, loc_coords: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
    """src node -> coords of the Location it points to (lowest Location id wins, deterministic)."""
    out: dict[int, tuple[float, float]] = {}
    for src, dst in edges[["_src", "_dst"]].sort_values(["_src", "_dst"]).itertuples(index=False):
        if src not in out and dst in loc_coords:
            out[int(src)] = loc_coords[dst]
    return out


def centroid_coords(edges: pd.DataFrame, member_coords: dict[int, tuple[float, float]],
                    member_side: str, group_side: str, stat: str = "mean") -> dict[int, tuple[float, float]]:
    """group node -> mean/median coords of its members along an edge table."""
    rows = [(g, *member_coords[m]) for m, g in edges[[member_side, group_side]].itertuples(index=False)
            if m in member_coords]
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["g", "lat", "lon"]).groupby("g")[["lat", "lon"]].agg(stat)
    return {int(g): (round(float(r.lat), 6), round(float(r.lon), 6)) for g, r in frame.iterrows()}
