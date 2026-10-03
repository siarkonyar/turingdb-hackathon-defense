"""Normalise a raw graph node (label + TuringDB property dict) into the API's Node shape.
Both backends feed raw property dicts through `make_node`, so mock and live data look identical."""

from __future__ import annotations

import math
from typing import Any, Mapping

from api.models import Kind, Node

KIND_BY_LABEL: dict[str, Kind] = {
    "PowerPlant": "plant",
    "Site": "site",
    "Supplier": "supplier",
    "Drone": "drone",
    "Crime": "crime",
    "Report": "report",
    "Part": "part",
    "Facility": "facility",  # supply_chain_deep
    "Port": "port",
    "Chokepoint": "chokepoint",
}
LABEL_BY_KIND: dict[str, str] = {kind: label for label, kind in KIND_BY_LABEL.items()}

STATUSES = frozenset({"at_risk", "lost", "no_power"})
MAX_PLANT_MW = 4000.0  # plants at or above this capacity get full importance
FIXED_IMPORTANCE: dict[str, float] = {
    "site": 1.0, "supplier": 0.7, "drone": 0.35, "crime": 0.25, "part": 0.3, "facility": 0.45, "port": 0.6,
    "chokepoint": 0.9, "other": 0.2,
}


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:  # pandas.NA refuses bool() conversion; NaN-likes are unequal to themselves
        return bool(value != value)
    except TypeError:
        return True


def clean(value: Any) -> Any:
    """Plain-Python JSON-safe scalar, or None for null/NaN/NA."""
    if is_missing(value):
        return None
    if hasattr(value, "item"):  # numpy / pandas scalar
        value = value.item()
    return value


def _float(value: Any) -> float | None:
    value = clean(value)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _str(value: Any) -> str | None:
    value = clean(value)
    return None if value is None else str(value)


def plant_importance(capacity_mw: float | None) -> float:
    if not capacity_mw or capacity_mw <= 0:
        return 0.05
    return max(0.05, min(1.0, math.log10(capacity_mw + 1) / math.log10(MAX_PLANT_MW + 1)))


def importance(kind: Kind, props: Mapping[str, Any]) -> float:
    if kind == "plant":
        return round(plant_importance(_float(props.get("capacity_mw"))), 4)
    if kind == "report":
        return _float(props.get("confidence")) or 0.5
    return FIXED_IMPORTANCE.get(kind, 0.5)


def _synthetic(props: Mapping[str, Any]) -> bool | None:
    flags = [clean(props.get(k)) for k in ("synthetic", "geo_synthetic")]
    present = [bool(f) for f in flags if f is not None]
    return any(present) if present else None


def make_node(node_id: str | int, label: str, props: Mapping[str, Any]) -> Node:
    kind = KIND_BY_LABEL.get(label, "other")
    status = _str(props.get("ops_status"))
    exposure = _float(props.get("exposure"))
    return Node(
        id=str(node_id),
        kind=kind,
        label=label,
        name=_str(props.get("name")) or _str(props.get("type")) or f"{label} {node_id}",
        lat=_float(props.get("latitude")),
        lon=_float(props.get("longitude")),
        source=_str(props.get("source")),
        timestamp=_str(props.get("timestamp")),
        synthetic=_synthetic(props),
        status=status if status in STATUSES else None,
        importance=importance(kind, props),
        fuel=_str(props.get("primary_fuel")),
        capacity_mw=_float(props.get("capacity_mw")),
        exposure=int(exposure) if exposure is not None else None,
        confidence=_float(props.get("confidence")),
    )


def with_status(node: Node, status: str | None) -> Node:
    return node.model_copy(update={"status": status if status in STATUSES else None})


def is_located(node: Node) -> bool:
    return node.lat is not None and node.lon is not None
