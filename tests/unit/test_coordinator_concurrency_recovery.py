"""Race and restart regressions for coordinator reservations and recovery."""

from __future__ import annotations

import json
import threading
import time

from apps.coordinator.network.server import CoordinatorState
from packages.crypto.trustfl_crypto.canonical import hash_parameters


class SlowStorage:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def save_artifact(self, *_args):
        self.started.set()
        self.release.wait(2)
        return type("Artifact", (), {"uri": "memory://update", "sha256_hash": "sha256:test"})()


def test_heartbeat_remains_responsive_and_duplicate_is_reserved_during_slow_storage():
    storage = SlowStorage()
    state = CoordinatorState(
        min_clients=2, num_rounds=1, storage_client=storage, require_signatures=False
    )
    assert state.register_client("a", {})
    assert state.register_client("b", {})
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(state.submit_update("a", 1, [[1.0]], 1, {}))
    )
    thread.start()
    assert storage.started.wait(1)
    started = time.monotonic()
    assert state.heartbeat("b", "IDLE") == 1
    assert time.monotonic() - started < 0.1
    assert not state.submit_update("a", 1, [[2.0]], 1, {})
    storage.release.set()
    thread.join(1)
    assert result == [True]


class MemoryStorage:
    def __init__(self, data: bytes):
        self.data = data

    def load_artifact(self, uri, _expected_hash):
        assert uri == "memory://global"
        return self.data


class RecoveryPersistence:
    def __init__(self, state):
        self.state = state

    def restore_state(self):
        return self.state


def test_restart_loads_global_model_from_artifact_and_restores_pending_nonce_state():
    parameters = [[1.25, 2.5]]
    state = {
        "current_round": 2,
        "registered_clients": {},
        "recovery_state": {
            "global_parameters": [],
            "pending_updates": {"client": {"update_id": "u", "num_examples": 1}},
            "verifier": {
                "current_round": 2,
                "accepted_model_versions": [hash_parameters(parameters)],
                "used_nonces": {"2": ["client:2:abcdef"]},
            },
        },
        "global_artifact": {
            "uri": "memory://global",
            "sha256_hash": "sha256:ignored",
            "model_version": hash_parameters(parameters),
        },
    }
    restored = CoordinatorState(
        persistence=RecoveryPersistence(state),
        storage_client=MemoryStorage(json.dumps(parameters).encode()),
        require_signatures=True,
    )
    assert restored.global_parameters == parameters
    assert "client" in restored.pending_updates
    assert "client:2:abcdef" in restored.update_verifier.nonce_store


def test_restart_rejects_global_artifact_with_wrong_model_version():
    state = {
        "current_round": 1,
        "registered_clients": {},
        "recovery_state": {},
        "global_artifact": {
            "uri": "memory://global",
            "sha256_hash": "x",
            "model_version": "sha256:wrong",
        },
    }
    restored = CoordinatorState(
        persistence=RecoveryPersistence(state), storage_client=MemoryStorage(b"[[1.0]]")
    )
    assert restored.global_parameters == []
