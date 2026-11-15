from apps.coordinator.network.server import CoordinatorState
from apps.coordinator.zkp_verifier import ProofVerificationResult, ZKPVerifier


def _proof():
    return {
        "pi_a": ["1", "2"],
        "pi_b": [["1", "2"], ["3", "4"]],
        "pi_c": ["1", "2"],
        "protocol": "groth16",
        "curve": "bn128",
    }


def test_malformed_proof_is_rejected_before_command():
    verifier = ZKPVerifier("true")
    result = verifier.verify(proof={}, public_signals=[], expected_signals=[])
    assert not result.valid
    assert result.reason == "MALFORMED_PROOF"


def test_public_signal_tampering_is_rejected():
    verifier = ZKPVerifier("true")
    result = verifier.verify(
        proof=_proof(),
        public_signals=["1", "9", "3", "4", "5"],
        expected_signals=["1", "2", "3", "4", "5"],
    )
    assert not result.valid
    assert result.reason == "PUBLIC_SIGNALS_MISMATCH"


def test_verifier_failure_is_fail_closed():
    verifier = ZKPVerifier("false")
    result = verifier.verify(
        proof=_proof(),
        public_signals=["1", "2", "3", "4", "5"],
        expected_signals=["1", "2", "3", "4", "5"],
    )
    assert not result.valid


class _RejectingVerifier:
    def verify(self, **_kwargs):
        return ProofVerificationResult(False, "INVALID_PROOF")


def test_coordinator_rejects_proof_before_side_effects():
    state = CoordinatorState(
        min_clients=1,
        num_rounds=1,
        require_signatures=False,
        require_zkp=True,
        zkp_verifier=_RejectingVerifier(),
    )
    assert state.register_client("client-1", {})
    assert not state.submit_update(
        "client-1",
        1,
        [[1.0]],
        1,
        {},
        {"model_version": "1", "public_commitment": "5"},
        proof=_proof(),
        public_signals=["1", "2", "3", "4", "5"],
    )
    assert state.pending_updates == {}
