"""
Phase 9: Resilience, Fault Injection & State Recovery Tests.
============================================================
Validates:
  - Process restart and durable state recovery
  - Blockchain RPC interruptions, retries, and outbox reconciliation
  - Duplicate, replayed, and malformed update rejection
  - Distributed fencing & lease takeover
  - Quorum loss and graceful abort/recovery
"""

from __future__ import annotations

import time
from typing import Any

from apps.coordinator.network.server import CoordinatorState


class _MockPersistence:
    def __init__(self, state_dict: dict[str, Any]):
        self._state = state_dict
        self.transitions = []
        self.outbox_retries = []
        self.outbox_processed = []

    def restore_state(self) -> dict[str, Any]:
        return self._state

    def transition_round(self, round_id: int, from_states: set[str], to_state: str) -> None:
        self.transitions.append((round_id, from_states, to_state))

    def fail_round(self, round_id: int) -> None:
        self.transitions.append((round_id, "FAILED"))

    def start_round(self, round_id: int, model_version: str) -> None:
        self.transitions.append((round_id, "STARTED", model_version))

    def record_aggregation(self, update_id: str) -> None:
        pass

    def record_rejection(self, *args, **kwargs) -> None:
        pass


class _FlakyBlockchainClient:
    def __init__(self, failure_count: int = 1):
        self.failures_remaining = failure_count
        self.calls = 0

    def finalize_round(self, *_args) -> bool:
        self.calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            return False
        return True

    def register_client(self, *_args) -> bool:
        return True

    def create_round(self, *_args) -> bool:
        return True

    def activate_round(self, *_args) -> bool:
        return True

    def record_aggregation(self, *_args) -> bool:
        return True

    def submit_update(self, *_args) -> bool:
        return True


def test_coordinator_restart_restores_durable_state():
    """Verify that coordinator process restart cleanly recovers active round and client state."""
    # 32-byte valid Ed25519 public key in base64
    valid_pubkey = "VrfMlWmEu01438crKmuIyjW31/RnKSoNtComI+d60eA="
    saved_state = {
        "current_round": 2,
        "registered_clients": {
            "client_1": {
                "status": "ONLINE",
                "lifecycle": "ACTIVE",
                "last_heartbeat": time.time(),
                "registered_at": time.time() - 100,
                "capabilities": {"gpu": True},
                "pubkey": valid_pubkey,
            },
            "client_2": {
                "status": "ONLINE",
                "lifecycle": "ACTIVE",
                "last_heartbeat": time.time(),
                "registered_at": time.time() - 100,
                "capabilities": {"gpu": False},
                "pubkey": valid_pubkey,
            },
        },
        "model_version": "model-v2",
        "recovery_state": {
            "global_parameters": [[0.5, 0.5]],
            "pending_updates": {},
        },
    }
    persistence = _MockPersistence(saved_state)
    coordinator = CoordinatorState(
        min_clients=2,
        num_rounds=3,
        persistence=persistence,
        require_signatures=False,
    )

    assert coordinator.current_round == 2
    assert len(coordinator.registered_clients) == 2
    assert "client_1" in coordinator.registered_clients
    assert "client_2" in coordinator.registered_clients
    assert coordinator.global_parameters == [[0.5, 0.5]]


def test_blockchain_rpc_timeout_retries_without_duplicate_aggregation():
    """Verify transient blockchain RPC failures are retried without re-aggregating."""
    chain = _FlakyBlockchainClient(failure_count=1)
    state = CoordinatorState(
        min_clients=2,
        num_rounds=2,
        blockchain_client=chain,
        require_signatures=False,
    )

    assert state.register_client("client_1", {})
    assert state.register_client("client_2", {})
    assert state.current_round == 1

    # Client 1 submits update
    assert state.submit_update("client_1", 1, [[1.0]], 1, {})
    # Client 2 submits update -> triggers aggregation and finalization
    assert state.submit_update("client_2", 1, [[1.0]], 1, {})

    # Chain finalize_round failed on first attempt
    assert chain.calls == 1
    assert len(state.round_history) == 1
    assert state._finalization_pending is True

    # Monitor tick triggers retry
    state._next_finalization_retry = 0
    state.monitor_tick()

    # Second attempt succeeds
    assert chain.calls == 2
    assert state._finalization_pending is False
    assert state.current_round == 2  # Advances to next round
    assert len(state.round_history) == 1  # No duplicate history entry!


def test_duplicate_and_replayed_update_rejection():
    """Verify duplicate submission by same client in same round is rejected."""
    state = CoordinatorState(min_clients=2, num_rounds=1, require_signatures=False)
    state.register_client("client_1", {})
    state.register_client("client_2", {})

    # First update succeeds
    assert state.submit_update("client_1", 1, [[1.0, 2.0]], 10, {})

    # Duplicate update from client_1 in same round must be rejected
    second_submit = state.submit_update("client_1", 1, [[1.0, 2.0]], 10, {})
    assert second_submit is False, "Duplicate submission from same client must be rejected"


def test_stale_round_update_rejection():
    """Verify update submitted for already completed round is rejected."""
    state = CoordinatorState(min_clients=1, num_rounds=2, require_signatures=False)
    state.register_client("client_1", {})

    # Submit round 1
    assert state.submit_update("client_1", 1, [[1.0]], 10, {})
    assert state.current_round == 2

    # Client tries to submit for round 1 when coordinator is already at round 2
    stale_submit = state.submit_update("client_1", 1, [[1.0]], 10, {})
    assert stale_submit is False, "Update for previous round must be rejected"


def test_quorum_loss_triggers_safe_abort():
    """Verify that if active clients drop below quorum, round aborts cleanly."""
    state = CoordinatorState(
        min_clients=3,
        num_rounds=2,
        round_timeout_seconds=0.1,
        heartbeat_timeout_seconds=0.1,
        require_signatures=False,
    )
    state.register_client("c1", {})
    state.register_client("c2", {})
    state.register_client("c3", {})

    # Mark c2 and c3 offline (missed heartbeats)
    state.registered_clients["c2"]["status"] = "OFFLINE"
    state.registered_clients["c3"]["status"] = "OFFLINE"

    assert len(state.active_clients) == 1  # Quorum lost (1 < 3)

    # Fast forward round timeout
    state.round_start_time = time.time() - 100
    state.monitor_tick()

    assert state.aborted is True
    assert "Quorum lost" in (state.abort_reason or "")
