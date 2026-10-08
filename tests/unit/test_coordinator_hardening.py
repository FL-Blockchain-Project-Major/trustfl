"""Regression tests for coordinator admission and quorum safety."""
from apps.coordinator.network.server import CoordinatorState


def _registered_state() -> CoordinatorState:
    state = CoordinatorState(min_clients=1, num_rounds=1, require_signatures=False)
    assert state.register_client("client-1", {})
    return state


def test_rejects_non_finite_or_wrong_shaped_update_before_aggregation():
    state = _registered_state()
    state.global_parameters = [[0.0, 0.0]]

    assert not state.submit_update("client-1", 1, [[float("nan"), 1.0]], 1, {})
    assert not state.submit_update("client-1", 1, [[1.0]], 1, {})
    assert state.pending_updates == {}


def test_duplicate_client_update_is_rejected():
    state = _registered_state()
    assert state.submit_update("client-1", 1, [[1.0]], 1, {})
    assert not state.submit_update("client-1", 1, [[2.0]], 1, {})


def test_timeout_without_quorum_records_failed_not_finalized():
    state = CoordinatorState(min_clients=2, num_rounds=1, require_signatures=False)
    assert state.register_client("client-1", {})
    assert state.register_client("client-2", {})
    assert state.submit_update("client-1", 1, [[1.0]], 1, {})

    with state.lock:
        state._aggregate_round_locked(timed_out=True)

    assert state.round_history == [{
        "round": 1,
        "num_successful_clients": 1,
        "timed_out": True,
        "status": "FAILED",
        "metrics": {},
    }]
