from trustfl_crypto.canonical import canonical_artifact_bytes

from apps.coordinator.network.server import _fedavg


def test_fedavg_independent_of_arrival_order():
    """Verify FedAvg aggregation produces identical global parameters regardless of arrival order."""
    # Create updates with slight float nuances and different client IDs
    u1 = {
        "client_id": "client-A",
        "parameters": [[0.10000000000000002, 0.20000000000000004], [0.3]],
        "num_examples": 100,
        "metrics": {"loss": 0.5},
    }
    u2 = {
        "client_id": "client-B",
        "parameters": [[0.10000000000000009, 0.2000000000000001], [0.30000000000000004]],
        "num_examples": 200,
        "metrics": {"loss": 0.4},
    }
    u3 = {
        "client_id": "client-C",
        "parameters": [[0.3, 0.4], [0.5]],
        "num_examples": 300,
        "metrics": {"loss": 0.3},
    }

    updates = [u1, u2, u3]

    # Compute aggregation with standard order
    res_base = _fedavg(updates)
    bytes_base = canonical_artifact_bytes(res_base, sum(u["num_examples"] for u in updates), {})

    # Test all permutations of arrival order
    orders = [
        [u1, u2, u3],
        [u3, u2, u1],
        [u2, u1, u3],
        [u2, u3, u1],
        [u1, u3, u2],
        [u3, u1, u2],
    ]

    for order in orders:
        res = _fedavg(order)
        order_ids = [u["client_id"] for u in order]
        assert res == res_base, f"FedAvg result differed for order: {order_ids}"
        bytes_order = canonical_artifact_bytes(res, sum(u["num_examples"] for u in updates), {})
        assert bytes_order == bytes_base, "Canonical artifact bytes differed across arrival orders"
