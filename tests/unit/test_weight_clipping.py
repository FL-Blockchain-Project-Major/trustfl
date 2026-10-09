from apps.coordinator.network.server import _fedavg


def test_weight_clipping_prevents_inflated_claim_from_dominating():
    result = _fedavg(
        [
            {"parameters": [[0.0]], "num_examples": 100},
            {"parameters": [[10.0]], "num_examples": 1_000_000},
        ]
    )
    assert result == [[5.0]]


def test_weight_clipping_is_independent_of_arrival_order():
    first = _fedavg(
        [
            {"parameters": [[1.0]], "num_examples": 100},
            {"parameters": [[3.0]], "num_examples": 300},
        ]
    )
    second = _fedavg(
        [
            {"parameters": [[3.0]], "num_examples": 300},
            {"parameters": [[1.0]], "num_examples": 100},
        ]
    )
    assert first == second == [[2.0]]
