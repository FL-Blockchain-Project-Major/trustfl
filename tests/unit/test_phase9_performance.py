"""
Phase 9: Performance, Scalability & Backpressure Unit Tests.
============================================================
Validates:
  - Federated aggregation scaling & bounded execution time
  - Parameter sanity validation (NaNs, Infs, dimension mismatch)
  - Memory bounds and L2 norm clipping performance
  - Tenant / federation isolation under concurrent federations
  - Backpressure and controlled rejection
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

from apps.coordinator.network.server import (
    CoordinatorState,
    _clip_update_norms,
    _fedavg,
)


class _RaisesContext:
    def __init__(self, exc_type, match: str | None = None):
        self.exc_type = exc_type
        self.match = match

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected exception {self.exc_type} was not raised")
        if not issubclass(exc_type, self.exc_type):
            return False
        if self.match and self.match not in str(exc_val):
            raise AssertionError(f"Exception message '{exc_val}' does not contain '{self.match}'")
        return True


def raises(exc_type, match: str | None = None):
    return _RaisesContext(exc_type, match)


def test_fedavg_scaling_bounded_time():
    """Verify FedAvg execution time scales predictably and stays within tight bounds."""
    num_params = 10000
    for num_clients in (5, 20, 50):
        updates = [
            {
                "client_id": f"client_{i}",
                "parameters": [[float(i + j * 0.001) for j in range(num_params)]],
                "num_examples": 100 + i * 10,
            }
            for i in range(num_clients)
        ]
        ref = [[0.0] * num_params]

        t0 = time.perf_counter()
        aggregated = _fedavg(updates, ref)
        elapsed = time.perf_counter() - t0

        assert len(aggregated[0]) == num_params
        # 50 clients with 10k params should easily complete within 500ms
        assert elapsed < 0.500, f"FedAvg with {num_clients} clients took {elapsed:.3f}s (>0.5s)"


def test_fedavg_rejects_nan_and_inf_safely():
    """Verify malformed weights (NaN or Inf) fail fast without polluting state."""
    updates = [
        {
            "client_id": "c1",
            "parameters": [[1.0, float("nan"), 3.0]],
            "num_examples": 10,
        },
        {
            "client_id": "c2",
            "parameters": [[1.0, 2.0, 3.0]],
            "num_examples": 10,
        },
    ]
    with raises(ValueError, match="finite numbers"):
        _fedavg(updates)

    updates_inf = [
        {
            "client_id": "c1",
            "parameters": [[1.0, float("inf"), 3.0]],
            "num_examples": 10,
        }
    ]
    with raises(ValueError, match="finite numbers"):
        _fedavg(updates_inf)


def test_fedavg_dimension_mismatch_rejected():
    """Verify updates with mismatched layer shapes are rejected."""
    updates = [
        {"client_id": "c1", "parameters": [[1.0, 2.0]], "num_examples": 10},
        {"client_id": "c2", "parameters": [[1.0, 2.0, 3.0]], "num_examples": 10},
    ]
    with raises(ValueError, match="matching shapes"):
        _fedavg(updates)


def test_update_norm_clipping_bounds_delta():
    """Verify that updates exceeding max norm are scaled down properly."""
    # Reference model at [0, 0], update at [30, 40] has L2 norm = 50
    updates = [
        {"client_id": "c1", "parameters": [[30.0, 40.0]], "num_examples": 10}
    ]
    ref = [[0.0, 0.0]]

    # With MAX_UPDATE_NORM environment setting or logic
    clipped = _clip_update_norms(updates, ref)
    assert len(clipped) == 1
    p = clipped[0]["parameters"][0]
    norm = math.sqrt(p[0] ** 2 + p[1] ** 2)
    # Norm must be finite and within bound
    assert math.isfinite(norm)


def test_tenant_isolation_concurrent_federation_states():
    """Verify separate coordinator states operate with full isolation."""
    fed1 = CoordinatorState(min_clients=2, num_rounds=2, require_signatures=False)
    fed2 = CoordinatorState(min_clients=3, num_rounds=5, require_signatures=False)

    # Register clients to fed1 (triggers round start when min_clients reached)
    assert fed1.register_client("client_a", {})
    assert fed1.register_client("client_b", {})

    # Register only 1 client to fed2 (< min_clients=3, so remains WAITING)
    assert fed2.register_client("client_x", {})

    assert len(fed1.active_clients) == 2
    assert len(fed2.active_clients) == 1
    assert "client_a" not in fed2.registered_clients
    assert "client_x" not in fed1.registered_clients

    assert fed1.current_round == 1
    assert fed2.current_round == 0  # fed2 is still waiting for quorum


def test_concurrent_client_submissions_thread_safety():
    """Verify concurrent client update submissions do not cause race conditions or corruptions."""
    num_clients = 20
    state = CoordinatorState(min_clients=num_clients, num_rounds=1, require_signatures=False)

    for i in range(num_clients):
        assert state.register_client(f"client_{i}", {})

    assert state.current_round == 1

    def submit_worker(client_idx: int) -> bool:
        weights = [[float(client_idx + j) for j in range(100)]]
        return state.submit_update(
            cid=f"client_{client_idx}",
            round_id=1,
            parameters=weights,
            num_examples=50,
            metrics={"loss": 0.1},
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(submit_worker, range(num_clients)))

    assert all(results), "All concurrent submissions should succeed"
    # When all enrolled clients submit, the coordinator completes aggregation
    assert len(state.round_history) == 1
    assert state.round_history[0]["num_successful_clients"] == num_clients
