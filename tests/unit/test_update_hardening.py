"""Regression tests: update-magnitude clipping and transient chain-failure handling."""

import math

import pytest

from apps.coordinator.network import server
from apps.coordinator.network.server import CoordinatorState, _fedavg


def _norm(params):
    return math.sqrt(sum(v * v for layer in params for v in layer))


def _updates(honest, attacker):
    return [
        {"client_id": "client_001", "parameters": honest, "num_examples": 48},
        {"client_id": "client_002", "parameters": attacker, "num_examples": 48},
    ]


def test_poisoned_update_dominates_when_clipping_disabled(monkeypatch):
    monkeypatch.setattr(server, "MAX_UPDATE_NORM", 0.0)
    result = _fedavg(_updates([[0.1, 0.1]], [[1000.0, 1000.0]]), [[0.0, 0.0]])
    assert _norm(result) > 100  # documents the unprotected behaviour


def test_update_norm_clipping_bounds_poisoned_update(monkeypatch):
    monkeypatch.setattr(server, "MAX_UPDATE_NORM", 1.0)
    reference = [[0.5, 0.5]]
    result = _fedavg(_updates([[0.6, 0.6]], [[1000.0, 1000.0]]), reference)
    # attacker delta clipped to norm 1.0; equal weights -> global moves by <= 0.5 + honest delta share
    assert _norm([[r - b for r, b in zip(result[0], reference[0], strict=True)]]) <= 1.0


def test_honest_update_below_bound_is_unchanged(monkeypatch):
    monkeypatch.setattr(server, "MAX_UPDATE_NORM", 10.0)
    result = _fedavg(_updates([[1.0, 2.0]], [[3.0, 4.0]]), [[0.0, 0.0]])
    assert result == [[2.0, 3.0]]


def test_clipping_without_reference_bounds_absolute_norm(monkeypatch):
    monkeypatch.setattr(server, "MAX_UPDATE_NORM", 1.0)
    result = _fedavg(_updates([[0.1, 0.1]], [[500.0, 500.0]]), None)
    assert _norm(result) <= 1.0 + 1e-9


def test_negative_norm_bound_is_rejected(monkeypatch):
    monkeypatch.setattr(server, "MAX_UPDATE_NORM", -1.0)
    with pytest.raises(ValueError):
        _fedavg(_updates([[0.1]], [[0.2]]), None)


def test_chain_call_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(server, "CHAIN_CALL_RETRY_BASE_SECONDS", 0.0)
    calls = {"n": 0}

    def flaky(*_args):
        calls["n"] += 1
        return calls["n"] >= 3

    CoordinatorState._chain_call_with_retry("X", flaky, 1)
    assert calls["n"] == 3


def test_chain_call_raises_oserror_after_retries(monkeypatch):
    monkeypatch.setattr(server, "CHAIN_CALL_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(server, "CHAIN_CALL_MAX_RETRIES", 3)
    with pytest.raises(OSError, match="BLOCKCHAIN_SUBMIT_FAILED"):
        CoordinatorState._chain_call_with_retry("BLOCKCHAIN_SUBMIT_FAILED", lambda *_a: False, 1)
