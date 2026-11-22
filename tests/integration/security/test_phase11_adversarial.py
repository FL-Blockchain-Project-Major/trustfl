"""Phase 11 Adversarial Security Tests.

Tests:
1. Invalid ZKP proof rejection (fail-closed verification)
2. Proof bypass attempts (require_zkp=true cannot be bypassed)
3. Replayed updates (nonce reuse and duplicate submission)
4. Unauthorized client updates (unregistered clients)
5. Cross-federation access controls (client submitting to another federation)
6. Key revocation and suspension enforcement (revoked/suspended keys rejected)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.api.api.db.models import Base, ClientLifecycleStatus
from apps.api.api.db.session import SessionLocal, engine
from apps.api.main import app
from apps.coordinator.network.server import CoordinatorState
from apps.coordinator.zkp_verifier import ProofVerificationResult, ZKPVerifier

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_adversarial_db():
    Base.metadata.create_all(bind=engine)
    # Federation A
    client.post(
        "/federations/",
        json={"id": "adv_fed_a", "name": "Adv Fed A", "min_clients": 2, "max_rounds": 5},
    )
    # Federation B
    client.post(
        "/federations/",
        json={"id": "adv_fed_b", "name": "Adv Fed B", "min_clients": 2, "max_rounds": 5},
    )
    # Clients in Fed A
    client.post(
        "/clients/",
        json={"id": "adv_client_a1", "federation_id": "adv_fed_a", "public_key_b64": "pubkey_a1"},
    )
    client.post(
        "/clients/",
        json={"id": "adv_client_a2", "federation_id": "adv_fed_a", "public_key_b64": "pubkey_a2"},
    )
    # Client in Fed B
    client.post(
        "/clients/",
        json={"id": "adv_client_b1", "federation_id": "adv_fed_b", "public_key_b64": "pubkey_b1"},
    )
    # Active Rounds
    client.post("/rounds/", json={"federation_id": "adv_fed_a", "round_number": 1})
    client.post("/rounds/", json={"federation_id": "adv_fed_b", "round_number": 1})

    yield
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# 1. Invalid Proof Verification & Fail-Closed Behavior
# ---------------------------------------------------------------------------


def test_invalid_proof_rejection_fail_closed():
    """Invalid or malformed ZKP proofs must be rejected and must fail closed."""
    verifier = ZKPVerifier(command="node packages/zkp/src/verify-cli.js")

    # Empty proof
    result = verifier.verify(
        proof={},
        public_signals=["1", "2", "3", "4", "5"],
        expected_signals=["1", "2", "3", "4", "5"],
    )
    assert not result.valid
    assert result.reason in ("MALFORMED_PROOF", "invalid_proof", "verification_failed")

    # Mismatched expected signals (valid shape, but wrong signals)
    valid_shape_proof = {
        "pi_a": ["1", "2", "1"],
        "pi_b": [["1", "2"], ["3", "4"], ["1", "0"]],
        "pi_c": ["1", "2", "1"],
        "protocol": "groth16",
        "curve": "bn128",
    }
    result_mismatch = verifier.verify(
        proof=valid_shape_proof,
        public_signals=["1", "2", "3", "4", "99999"],
        expected_signals=["1", "2", "3", "4", "5"],
    )
    assert not result_mismatch.valid
    assert result_mismatch.reason == "PUBLIC_SIGNALS_MISMATCH"


def test_coordinator_rejects_invalid_zkp_proof():
    """Coordinator must reject updates when ZKP verification returns invalid."""
    mock_zkp = MagicMock(spec=ZKPVerifier)
    mock_zkp.verify.return_value = ProofVerificationResult(valid=False, reason="invalid_proof")

    state = CoordinatorState(
        min_clients=1,
        num_rounds=3,
        require_signatures=False,
        require_zkp=True,
        zkp_verifier=mock_zkp,
    )
    state.current_round = 1
    state._round_active = True
    state.register_client("client_001", capabilities={})

    ok = state.submit_update(
        cid="client_001",
        round_id=1,
        parameters=[[0.05, 0.15]],
        num_examples=10,
        metrics={"loss": 0.5},
        metadata={"model_version": "v1", "public_commitment": "123"},
        proof={"pi_a": ["bad"]},
        public_signals=["s1", "s2", "s3", "s4", "s5"],
    )
    assert ok is False, "Coordinator must reject update with invalid ZKP proof"


# ---------------------------------------------------------------------------
# 2. Proof Bypass Attempts
# ---------------------------------------------------------------------------


def test_coordinator_blocks_proof_bypass_when_zkp_required():
    """When require_zkp is enabled, submitting without proof or signals must be rejected."""
    mock_zkp = MagicMock(spec=ZKPVerifier)
    state = CoordinatorState(
        min_clients=1,
        num_rounds=3,
        require_signatures=False,
        require_zkp=True,
        zkp_verifier=mock_zkp,
    )
    state.current_round = 1
    state._round_active = True
    state.register_client("client_001", capabilities={})

    # Attempt 1: None proof
    ok1 = state.submit_update(
        cid="client_001",
        round_id=1,
        parameters=[[0.05, 0.15]],
        num_examples=10,
        metrics={"loss": 0.5},
        metadata={"model_version": "v1", "public_commitment": "123"},
        proof=None,
        public_signals=["s1", "s2", "s3", "s4", "s5"],
    )
    assert ok1 is False

    # Attempt 2: None public_signals
    ok2 = state.submit_update(
        cid="client_001",
        round_id=1,
        parameters=[[0.05, 0.15]],
        num_examples=10,
        metrics={"loss": 0.5},
        metadata={"model_version": "v1", "public_commitment": "123"},
        proof={"pi_a": ["1"]},
        public_signals=None,
    )
    assert ok2 is False

    # Attempt 3: Empty metadata
    ok3 = state.submit_update(
        cid="client_001",
        round_id=1,
        parameters=[[0.05, 0.15]],
        num_examples=10,
        metrics={"loss": 0.5},
        metadata=None,
        proof={"pi_a": ["1"]},
        public_signals=["s1"],
    )
    assert ok3 is False


# ---------------------------------------------------------------------------
# 3. Replay Attacks
# ---------------------------------------------------------------------------


def test_replayed_update_nonce_rejection():
    """Replaying an update nonce within the same round must be rejected (HTTP 400)."""
    payload1 = {
        "id": "upd_adv_replay_1",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_a1",
        "nonce": "unique_nonce_adv_1",
    }
    r1 = client.post("/updates/", json=payload1)
    assert r1.status_code == 200

    # Client A2 attempts to replay Client A1's nonce
    payload2 = {
        "id": "upd_adv_replay_2",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_a2",
        "nonce": "unique_nonce_adv_1",
    }
    r2 = client.post("/updates/", json=payload2)
    assert r2.status_code == 400
    assert "Nonce already used" in r2.json()["detail"]


def test_replayed_client_submission_in_same_round():
    """Client submitting a second update in the same round must be rejected (HTTP 400)."""
    payload = {
        "id": "upd_adv_dup_client",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_a1",
        "nonce": "another_nonce_adv_2",
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 400
    assert "Client already submitted" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Unauthorized Clients
# ---------------------------------------------------------------------------


def test_unauthorized_unknown_client_rejected():
    """Unknown client not in registry must be rejected."""
    payload = {
        "id": "upd_adv_unknown",
        "round_id": "adv_fed_a_round1",
        "client_id": "ghost_client_999",
        "nonce": "ghost_nonce_1",
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 404
    assert "Resource not found" in r.json()["detail"]

    # Also test coordinator state rejection
    state = CoordinatorState(min_clients=1, num_rounds=3)
    state.current_round = 1
    state._round_active = True
    ok = state.submit_update(
        cid="unregistered_adversary",
        round_id=1,
        parameters=[[0.05, 0.15]],
        num_examples=10,
        metrics={"loss": 0.5},
    )
    assert ok is False, "Coordinator must reject unregistered client"


# ---------------------------------------------------------------------------
# 5. Cross-Federation Access
# ---------------------------------------------------------------------------


def test_cross_federation_access_blocked():
    """Client from Federation B must be blocked from submitting to Federation A round."""
    payload = {
        "id": "upd_adv_cross_fed",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_b1",  # Belongs to adv_fed_b
        "nonce": "cross_fed_nonce_1",
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 404, "Cross-federation submission must return 404 (not found)"


# ---------------------------------------------------------------------------
# 6. Key Revocation and Suspension
# ---------------------------------------------------------------------------


def test_revoked_key_rejection():
    """Client whose key has been revoked must not be allowed to submit updates."""
    # Register client to revoke
    client.post(
        "/clients/",
        json={"id": "adv_client_revoked", "federation_id": "adv_fed_a", "public_key_b64": "key_rev"},
    )
    # Revoke client
    db = SessionLocal()
    from apps.api.api.db.models import Client as DBClient

    c = db.query(DBClient).filter(DBClient.id == "adv_client_revoked").one()
    c.lifecycle_status = ClientLifecycleStatus.REVOKED
    c.is_active = False
    db.commit()
    db.close()

    payload = {
        "id": "upd_adv_revoked",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_revoked",
        "nonce": "revoked_nonce_1",
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 403
    assert "key is not active" in r.json()["detail"]


def test_suspended_key_rejection():
    """Client whose key has been suspended must not be allowed to submit updates."""
    # Register client to suspend
    client.post(
        "/clients/",
        json={"id": "adv_client_suspended", "federation_id": "adv_fed_a", "public_key_b64": "key_susp"},
    )
    # Suspend client
    db = SessionLocal()
    from apps.api.api.db.models import Client as DBClient

    c = db.query(DBClient).filter(DBClient.id == "adv_client_suspended").one()
    c.lifecycle_status = ClientLifecycleStatus.SUSPENDED
    c.is_active = False
    db.commit()
    db.close()

    payload = {
        "id": "upd_adv_suspended",
        "round_id": "adv_fed_a_round1",
        "client_id": "adv_client_suspended",
        "nonce": "suspended_nonce_1",
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 403
    assert "key is not active" in r.json()["detail"]
