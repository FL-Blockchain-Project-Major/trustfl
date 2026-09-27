"""Unit tests for UpdateSigner and UpdateVerifier."""
from __future__ import annotations

import time
import unittest

from trustfl_crypto.keys import ClientIdentity, PublicKeyRegistry
from trustfl_crypto.signer import SignedUpdate, UpdateSigner
from trustfl_crypto.verifier import UpdateVerifier, VerificationStatus


PARAMS = [[0.1, 0.2, 0.3], [0.9, 0.8]]
FED_ID = "fed-test"
MODEL_VER = "sha256:deadbeef"


def _setup(
    client_id: str = "c1",
    round_id: int = 1,
    clock_skew: float = 60.0,
):
    """Create a matched (identity, signer, registry, verifier) tuple."""
    identity = ClientIdentity.generate(client_id)
    registry = PublicKeyRegistry()
    registry.register(client_id, identity.public_key_b64)
    signer = UpdateSigner(identity, FED_ID)
    verifier = UpdateVerifier(registry, clock_skew_seconds=clock_skew)
    verifier.set_round(round_id, accepted_model_versions={MODEL_VER})
    return identity, signer, registry, verifier


class TestSignerAndVerifier(unittest.TestCase):

    # ------------------------------------------------------------------
    # Happy path

    def test_valid_update_is_accepted(self):
        _, signer, _, verifier = _setup()
        signed = signer.sign(
            round_id=1,
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=50,
            metrics={"loss": 0.3},
        )
        result = verifier.verify(signed, expected_client_id="c1")
        self.assertTrue(result.ok, f"Expected OK, got {result}")

    def test_signed_update_roundtrip_via_dict(self):
        _, signer, _, verifier = _setup()
        signed = signer.sign(
            round_id=1,
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=50,
            metrics={"loss": 0.3},
        )
        # Simulate wire serialisation/deserialisation
        wire = signed.to_dict()
        restored = SignedUpdate.from_dict(wire)
        result = verifier.verify(restored, expected_client_id="c1")
        self.assertTrue(result.ok, f"Roundtrip failed: {result}")

    # ------------------------------------------------------------------
    # Invalid signature

    def test_tampered_signature_rejected(self):
        _, signer, _, verifier = _setup()
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER, parameters=PARAMS,
            num_examples=50, metrics={},
        )
        bad_sig = bytearray(signed.signature)
        bad_sig[0] ^= 0xFF
        tampered = SignedUpdate(
            metadata=signed.metadata,
            signature=bytes(bad_sig),
            parameters=signed.parameters,
            num_examples=signed.num_examples,
            metrics=signed.metrics,
        )
        result = verifier.verify(tampered, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.INVALID_SIGNATURE)

    def test_signature_from_different_key_rejected(self):
        _, signer1, registry, verifier = _setup()
        # signer2 uses a different private key but the same client_id label
        identity2 = ClientIdentity.generate("c1")
        signer2 = UpdateSigner(identity2, FED_ID)
        signed = signer2.sign(
            round_id=1, model_version=MODEL_VER, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        # registry still has the original key → verify fails
        result = verifier.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.INVALID_SIGNATURE)

    # ------------------------------------------------------------------
    # Wrong client

    def test_wrong_client_in_request_rejected(self):
        _, signer, _, verifier = _setup(client_id="c1")
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        result = verifier.verify(signed, expected_client_id="c2")  # mismatch
        self.assertEqual(result.status, VerificationStatus.WRONG_CLIENT)

    # ------------------------------------------------------------------
    # Wrong round

    def test_wrong_round_in_metadata_rejected(self):
        _, signer, _, verifier = _setup(round_id=1)
        signed = signer.sign(
            round_id=2,           # metadata says 2, server is at 1
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=10,
            metrics={},
        )
        result = verifier.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.WRONG_ROUND)

    # ------------------------------------------------------------------
    # Unknown client

    def test_unregistered_client_rejected(self):
        identity = ClientIdentity.generate("unknown")
        registry = PublicKeyRegistry()
        # deliberately NOT registering "unknown"
        signer = UpdateSigner(identity, FED_ID)
        verifier = UpdateVerifier(registry)
        verifier.set_round(1)
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        result = verifier.verify(signed, expected_client_id="unknown")
        self.assertEqual(result.status, VerificationStatus.UNKNOWN_CLIENT)

    # ------------------------------------------------------------------
    # Artifact hash mismatch

    def test_changed_parameters_rejected(self):
        _, signer, _, verifier = _setup()
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        # Tamper with parameters after signing
        bad = SignedUpdate(
            metadata=signed.metadata,
            signature=signed.signature,
            parameters=[[9.9, 9.9]],   # different from what was signed
            num_examples=signed.num_examples,
            metrics=signed.metrics,
        )
        result = verifier.verify(bad, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.ARTIFACT_HASH_MISMATCH)

    # ------------------------------------------------------------------
    # Stale model version

    def test_stale_model_version_rejected(self):
        _, signer, _, verifier = _setup()
        signed = signer.sign(
            round_id=1,
            model_version="sha256:oldoldold",  # not in accepted_versions
            parameters=PARAMS,
            num_examples=10,
            metrics={},
        )
        result = verifier.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.STALE_MODEL_VERSION)

    # ------------------------------------------------------------------
    # Timestamp drift

    def test_future_timestamp_rejected(self):
        _, signer, _, verifier = _setup(clock_skew=5.0)
        future_ts = int(time.time()) + 3600   # 1 hour in the future
        from trustfl_crypto.canonical import (
            UpdateMetadata, generate_nonce, hash_parameters
        )
        meta = UpdateMetadata(
            federation_id=FED_ID,
            round_id=1,
            client_id="c1",
            model_version=MODEL_VER,
            update_id="u-001",
            artifact_hash=hash_parameters(PARAMS),
            timestamp=future_ts,
            nonce=generate_nonce("c1", 1),
        )
        identity = ClientIdentity.generate("c1")
        registry = PublicKeyRegistry()
        registry.register("c1", identity.public_key_b64)
        verifier2 = UpdateVerifier(registry, clock_skew_seconds=5.0)
        verifier2.set_round(1)
        sig = identity.sign(meta.canonical_bytes())
        signed = SignedUpdate(
            metadata=meta, signature=sig, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        result = verifier2.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.TIMESTAMP_DRIFT)

    def test_past_timestamp_rejected(self):
        _, signer, _, verifier = _setup(clock_skew=5.0)
        old_ts = int(time.time()) - 3600
        from trustfl_crypto.canonical import (
            UpdateMetadata, generate_nonce, hash_parameters
        )
        meta = UpdateMetadata(
            federation_id=FED_ID,
            round_id=1,
            client_id="c1",
            model_version=MODEL_VER,
            update_id="u-002",
            artifact_hash=hash_parameters(PARAMS),
            timestamp=old_ts,
            nonce=generate_nonce("c1", 1),
        )
        identity = ClientIdentity.generate("c1")
        registry = PublicKeyRegistry()
        registry.register("c1", identity.public_key_b64)
        verifier2 = UpdateVerifier(registry, clock_skew_seconds=5.0)
        verifier2.set_round(1)
        sig = identity.sign(meta.canonical_bytes())
        signed = SignedUpdate(
            metadata=meta, signature=sig, parameters=PARAMS,
            num_examples=10, metrics={},
        )
        result = verifier2.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.TIMESTAMP_DRIFT)


if __name__ == "__main__":
    unittest.main()
