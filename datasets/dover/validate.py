"""Data integrity and cascade-depth checks, without answering scenario questions."""
from __future__ import annotations

from collections import defaultdict, deque

from api.deep_cascade import Seeds, SupplyNetwork, propagate
from datasets.dover.model import BOUNDS, SOURCE, Corridor


def validate(c: Corridor) -> dict:
    g = c.graph
    assert len(c.ids) == len(g.nodes), "duplicate stable identifiers"
    property_types: dict[str, type] = {}
    for n in g.nodes:
        assert n.props["source"] == SOURCE and n.props["synthetic"] is True
        if "latitude" in n.props:
            assert BOUNDS[0] <= n.props["longitude"] <= BOUNDS[2]
            assert BOUNDS[1] <= n.props["latitude"] <= BOUNDS[3]
    for record in (*g.nodes, *g.edges):
        for key, value in record.props.items():
            assert key not in property_types or property_types[key] is type(value), f"mixed type: {key}"
            property_types[key] = type(value)
    assert all(0 <= e.start < len(g.nodes) and 0 <= e.end < len(g.nodes) for e in g.edges)
    assert all(e.props["source"] == SOURCE for e in g.edges)
    deps = defaultdict(list)
    out = defaultdict(list)
    for e in g.edges:
        out[e.start].append(e)
        if e.edge_type == "DEPENDS_ON":
            deps[e.start].append(e.end)
    # Active dependency DAG must terminate; recovery requirements are separate and dormant.
    degree = [0] * len(g.nodes)
    for targets in deps.values():
        for target in targets:
            degree[target] += 1
    queue = deque(i for i, count in enumerate(degree) if count == 0)
    seen = 0
    while queue:
        i = queue.popleft()
        seen += 1
        for target in deps[i]:
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
    assert seen == len(g.nodes), "active dependency cycle"
    for i, n in enumerate(g.nodes):
        if n.labels[0] in ("Facility", "Port", "PowerPlant", "Chokepoint"):
            options = [e.end for e in out[i] if e.edge_type == "HAS_RECOVERY"]
            assert options, f"no recovery option for {n.props['entity_id']}"
        if n.labels == ("RecoveryOption",):
            assert n.props["active"] is False
            assert any(e.edge_type == "REQUIRES" for e in out[i]), "ungrounded recovery"
    # Strait closure affects sea access only, not independent crossing alternatives.
    strait = c.ids["chokepoint:dover"]
    assert strait in deps[c.ids["route:dover_calais"]]
    assert strait in deps[c.ids["route:dover_dunkirk"]]
    for route in ("tunnel", "western_channel", "london_paris_air", "kent_beauvais_air"):
        assert strait not in deps[c.ids[f"route:{route}"]]
    # Aggregate baseline scheduled cargo fits shared two-way ferry capacity.
    tonnes = sum(n.props["tonnes"] for n in g.nodes if n.labels == ("Consignment",))
    capacity = g.nodes[c.ids["route:dover_calais"]].props["capacity_tonnes_day"]
    assert tonnes <= capacity, "baseline already overloads primary crossing"
    for town in ("dover", "calais"):
        for role in ("road_hub", "customs_hub"):
            assert tonnes <= g.nodes[c.ids[f"transport:{town}:{role}"]].props["throughput_tonnes_day"]
    supply = SupplyNetwork.from_edges(
        (g.nodes[e.start].props["entity_id"], g.nodes[e.end].props["entity_id"], e.props["annual_volume"])
        for e in g.edges if e.edge_type == "SUPPLIES")
    roots = {n.props["entity_id"]: 1.0 for n in g.nodes
             if n.labels == ("Facility",) and n.props["role"] == "inputs"}
    layers = propagate(Seeds(roots, degree=1, via="TRANSITED"), supply)
    assert len(layers) == 12, "corridor must exercise the complete 12-degree display cascade"
    affected = sum(len(layer) for layer in layers)
    assert affected >= 700, "insufficient branching reach"
    demands = [n for n in g.nodes if n.labels == ("Demand",)]
    assert len(demands) == 260
    assert abs(tonnes - sum(n.props["tonnes_day"] * 0.6 for n in demands)) < 1e-6
    return dict(source=SOURCE, nodes=len(g.nodes), edges=len(g.edges),
                labels=dict(sorted(g.label_counts().items())),
                relationships=dict(sorted(g.edge_counts().items())),
                towns=26, sectors=10, display_cascade_degrees=len(layers),
                strait_display_affected_facilities=affected,
                primary_cargo_tonnes_day=round(tonnes, 3),
                primary_capacity_tonnes_day=capacity, bounds=list(BOUNDS))
