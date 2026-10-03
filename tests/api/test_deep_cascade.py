"""Volume-weighted cascade engine (pure). Networks are hand-built so every severity is checkable by hand."""

from __future__ import annotations

import pytest

from api.deep_cascade import MAX_DEGREE, Hit, Seeds, SupplyNetwork, impact_score, propagate


def net(*edges: tuple[str, str, float]) -> SupplyNetwork:
    return SupplyNetwork.from_edges(edges)


def by_degree(layers: list[list[Hit]]) -> list[dict[str, float]]:
    return [{h.facility_id: h.severity for h in layer} for layer in layers]


def test_from_edges_sums_inbound_and_treats_missing_volume_as_zero():
    n = net(("A", "C", 6.0), ("B", "C", 4.0), ("A", "D", None))  # type: ignore[arg-type]
    assert n.inbound == {"C": 10.0, "D": 0.0}
    assert n.out_edges["A"] == (("C", 6.0), ("D", 0.0))


def test_chain_attenuates_by_inbound_share():
    n = net(("A", "B", 10.0), ("B", "C", 5.0), ("X", "C", 15.0))
    layers = propagate(Seeds({"A": 1.0}, degree=1, via="TRANSITED"), n)
    assert by_degree(layers) == [{"A": 1.0}, {"B": 1.0}, {"C": 0.25}]
    assert [h.degree for layer in layers for h in layer] == [1, 2, 3]
    assert layers[0][0].parent is None and layers[0][0].via == "TRANSITED"
    assert layers[2][0].parent == "B" and layers[2][0].via == "SUPPLIES"


def test_below_threshold_is_dropped_and_does_not_propagate():
    n = net(("A", "B", 1.0), ("Y", "B", 99.0), ("B", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), n, min_severity=0.05)
    assert by_degree(layers) == [{"A": 1.0}]  # B gets 0.01 < 0.05, so C is never reached


def test_multiple_affected_suppliers_add_up_and_parent_is_biggest_contributor():
    n = net(("A", "C", 6.0), ("B", "C", 4.0), ("Z", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0, "B": 0.5}, 1, "TRANSITED"), n)
    hit = layers[1][0]
    assert hit.facility_id == "C" and hit.severity == pytest.approx(0.4)  # (6*1 + 4*0.5) / 20
    assert hit.parent == "A"


def test_parent_tie_goes_to_smaller_facility_id():
    n = net(("B", "C", 5.0), ("A", "C", 5.0))
    layers = propagate(Seeds({"A": 1.0, "B": 1.0}, 1, "TRANSITED"), n)
    assert layers[1][0].parent == "A"


def test_node_is_assigned_once_at_its_first_degree():
    n = net(("A", "B", 1.0), ("A", "C", 1.0), ("B", "C", 1.0))
    layers = propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), n)
    assert [sorted(d) for d in by_degree(layers)] == [["A"], ["B", "C"]]


def test_facility_origin_is_not_returned_and_cycles_terminate():
    n = net(("O", "B", 1.0), ("B", "O", 1.0), ("B", "C", 1.0))
    layers = propagate(Seeds({"O": 1.0}, degree=0, via="SUPPLIES"), n)
    assert by_degree(layers) == [{"B": 1.0}, {"C": 1.0}]
    assert layers[0][0].degree == 1 and layers[0][0].parent == "O"


def test_no_buyers_yields_no_layers():
    assert propagate(Seeds({"O": 1.0}, 0, "SUPPLIES"), net(("X", "Y", 1.0))) == []


def test_seeds_below_threshold_are_dropped():
    layers = propagate(Seeds({"A": 0.02, "B": 0.9}, 1, "TRANSITED"), net())
    assert by_degree(layers) == [{"B": 0.9}]


def test_layers_sorted_by_severity_then_id():
    layers = propagate(Seeds({"B": 0.5, "A": 0.5, "C": 0.9}, 1, "TRANSITED"), net())
    assert [h.facility_id for h in layers[0]] == ["C", "A", "B"]


def test_max_degree_caps_depth():
    chain = [(f"F{i}", f"F{i + 1}", 1.0) for i in range(30)]
    layers = propagate(Seeds({"F0": 1.0}, 1, "TRANSITED"), net(*chain))
    assert len(layers) == MAX_DEGREE and layers[-1][0].degree == MAX_DEGREE
    assert len(propagate(Seeds({"F0": 1.0}, 1, "TRANSITED"), net(*chain), max_degree=3)) == 3


def test_severity_is_capped_at_one():
    n = net(("A", "C", 10.0), ("B", "C", 10.0))
    layers = propagate(Seeds({"A": 1.0, "B": 1.0}, 1, "TRANSITED"), n)
    assert layers[1][0].severity == 1.0


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_invalid_min_severity_raises(bad: float):
    with pytest.raises(ValueError):
        propagate(Seeds({"A": 1.0}, 1, "TRANSITED"), net(), min_severity=bad)


def test_invalid_seed_degree_raises():
    with pytest.raises(ValueError):
        propagate(Seeds({"A": 1.0}, 2, "TRANSITED"), net())


def test_impact_score_sums_severity_to_two_decimals():
    layers = [[Hit("A", 1, 1.0, None, "TRANSITED")], [Hit("B", 2, 0.333, "A", "SUPPLIES"),
                                                      Hit("C", 2, 0.25, "A", "SUPPLIES")]]
    assert impact_score(layers) == 1.58


def test_chokepoint_nodes_normalise_with_coordinates():
    from api.nodes import make_node

    node = make_node(7, "Chokepoint", {"name": "Strait of Hormuz", "latitude": 26.5, "longitude": 56.4})
    assert node.kind == "chokepoint" and node.lat == 26.5 and node.lon == 56.4 and node.importance == 0.9
