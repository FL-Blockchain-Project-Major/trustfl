"""Unit tests for replay protection mechanisms."""
from __future__ import annotations

import time
import unittest

from trustfl_crypto.canonical import generate_nonce, hash_parameters, UpdateMetadata
from trustfl_crypto.keys import ClientIdentity, PublicKeyRegistry
from trustfl_crypto.signer import SignedUpdate, UpdateSigner
from trustfl_crypto.verifier import (
    NonceStore,
    UpdateVerifier,
    VerificationStatus,
    _nonce_well_formed,
)

PARAMS = [[0.5, 0.5]]
FED_ID = "fed-001"
MODEL_VER = "sha256:aabbccdd"


def _make_verifier(client_id="c1", round_id=1):
    identity = ClientIdentity.generate(client_id)
    registry = PublicKeyRegistry()
    registry.register(client_id, identity.public_key_b64)
    signer = UpdateSigner(identity, FED_ID)
    verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
    verifier.set_round(round_id, accepted_model_versions={MODEL_VER})
    return identity, signer, verifier


class TestNonceStore(unittest.TestCase):

    def test_fresh_nonce_is_accepted(self):
        store = NonceStore()
        nonce = generate_nonce("c1", 1)
        self.assertTrue(store.check_and_add(nonce, 1))

    def test_reused_nonce_is_rejected(self):
        store = NonceStore()
        nonce = generate_nonce("c1", 1)
        store.check_and_add(nonce, 1)
        self.assertFalse(store.check_and_add(nonce, 1))

    def test_same_nonce_different_rounds_each_accepted(self):
        """
        Nonces are round-scoped; identical random part in different rounds
        is an unlikely but theoretically acceptable collision.
        """
        store = NonceStore()
        nonce = "c1:1:abcdef1234567890"
        self.assertTrue(store.check_and_add(nonce, 1))
        # A nonce with round=2 in a different bucket is a different key
        nonce2 = "c1:2:abcdef1234567890"
        self.assertTrue(store.check_and_add(nonce2, 2))

    def test_evict_rounds_before_clears_old_nonces(self):
        store = NonceStore()
        nonce = generate_nonce("c1", 1)
        store.check_and_add(nonce, 1)
        store.evict_rounds_before(2)
        # After eviction, the old nonce is gone from memory
        self.assertNotIn(nonce, store)

    def test_concurrent_nonce_checks_are_safe(self):
        import threading
        store = NonceStore()
        results = []
        nonce = generate_nonce("c1", 1)

        def attempt():
            results.append(store.check_and_add(nonce, 1))

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly one thread should have succeeded
        self.assertEqual(sum(results), 1, "Only one concurrent nonce add should succeed")


class TestReplayProtection(unittest.TestCase):

    def test_replayed_update_rejected(self):
        """Submit the same signed update twice; second must be rejected."""
        _, signer, verifier = _make_verifier()
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER,
            parameters=PARAMS, num_examples=10, metrics={},
        )
        r1 = verifier.verify(signed, expected_client_id="c1")
        self.assertTrue(r1.ok, f"First submission should succeed: {r1}")
        r2 = verifier.verify(signed, expected_client_id="c1")
        self.assertEqual(r2.status, VerificationStatus.REUSED_NONCE,
                         f"Second submission should be rejected as replay: {r2}")

    def test_each_new_sign_produces_different_nonce(self):
        """Two fresh sign() calls produce different nonces → both accepted."""
        _, signer, verifier = _make_verifier()
        s1 = signer.sign(round_id=1, model_version=MODEL_VER,
                         parameters=PARAMS, num_examples=10, metrics={})
        s2 = signer.sign(round_id=1, model_version=MODEL_VER,
                         parameters=PARAMS, num_examples=10, metrics={})
        self.assertNotEqual(s1.metadata.nonce, s2.metadata.nonce)
        r1 = verifier.verify(s1, expected_client_id="c1")
        r2 = verifier.verify(s2, expected_client_id="c1")
        self.assertTrue(r1.ok, str(r1))
        self.assertTrue(r2.ok, str(r2))

    def test_cross_client_nonce_reuse_rejected(self):
        """c2 cannot reuse c1's nonce (wrong client check fires first)."""
        id1 = ClientIdentity.generate("c1")
        id2 = ClientIdentity.generate("c2")
        registry = PublicKeyRegistry()
        registry.register("c1", id1.public_key_b64)
        registry.register("c2", id2.public_key_b64)
        signer1 = UpdateSigner(id1, FED_ID)
        signer2 = UpdateSigner(id2, FED_ID)
        verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
        verifier.set_round(1, accepted_model_versions={MODEL_VER})

        s1 = signer1.sign(round_id=1, model_version=MODEL_VER,
                          parameters=PARAMS, num_examples=10, metrics={})
        s2 = signer2.sign(round_id=1, model_version=MODEL_VER,
                          parameters=PARAMS, num_examples=10, metrics={})

        verifier.verify(s1, expected_client_id="c1")   # accepted

        # Try to re-submit s1 as if it were from c2 → WRONG_CLIENT (meta says c1)
        result = verifier.verify(s1, expected_client_id="c2")
        self.assertEqual(result.status, VerificationStatus.WRONG_CLIENT)

    def test_round_advance_old_nonce_not_reusable(self):
        """After round advances, old nonces are evicted but stale round check fires."""
        _, signer, verifier = _make_verifier(round_id=1)
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER,
            parameters=PARAMS, num_examples=10, metrics={},
        )
        verifier.verify(signed, expected_client_id="c1")  # accepted round 1

        # Advance to round 2
        verifier.set_round(2, accepted_model_versions={MODEL_VER})
        # Attempt to replay old round-1 update → WRONG_ROUND
        result = verifier.verify(signed, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.WRONG_ROUND)


class TestNonceWellFormed(unittest.TestCase):

    def test_valid_nonce(self):
        nonce = generate_nonce("c1", 3)
        self.assertTrue(_nonce_well_formed(nonce, "c1", 3))

    def test_wrong_client_in_nonce(self):
        nonce = generate_nonce("c1", 3)
        self.assertFalse(_nonce_well_formed(nonce, "c2", 3))

    def test_wrong_round_in_nonce(self):
        nonce = generate_nonce("c1", 3)
        self.assertFalse(_nonce_well_formed(nonce, "c1", 4))

    def test_too_short_random_part(self):
        self.assertFalse(_nonce_well_formed("c1:1:abc", "c1", 1))

    def test_non_hex_random_part(self):
        self.assertFalse(_nonce_well_formed("c1:1:not_hex_part_1234", "c1", 1))

    def test_missing_separator(self):
        self.assertFalse(_nonce_well_formed("onlyonepart", "c1", 1))

    def test_malformed_nonce_rejected_by_verifier(self):
        _, signer, verifier = _make_verifier()
        signed = signer.sign(
            round_id=1, model_version=MODEL_VER,
            parameters=PARAMS, num_examples=10, metrics={},
        )
        # Overwrite with a malformed nonce
        bad_meta = UpdateMetadata(
            federation_id=signed.metadata.federation_id,
            round_id=signed.metadata.round_id,
            client_id=signed.metadata.client_id,
            model_version=signed.metadata.model_version,
            update_id=signed.metadata.update_id,
            artifact_hash=signed.metadata.artifact_hash,
            timestamp=signed.metadata.timestamp,
            nonce="MALFORMED",
        )
        identity = ClientIdentity.generate("c1")
        registry = PublicKeyRegistry()
        registry.register("c1", identity.public_key_b64)
        v2 = UpdateVerifier(registry, clock_skew_seconds=60.0)
        v2.set_round(1, accepted_model_versions={MODEL_VER})
        bad_sig = identity.sign(bad_meta.canonical_bytes())
        bad = SignedUpdate(
            metadata=bad_meta, signature=bad_sig,
            parameters=PARAMS, num_examples=10, metrics={},
        )
        result = v2.verify(bad, expected_client_id="c1")
        self.assertEqual(result.status, VerificationStatus.NONCE_MALFORMED)


if __name__ == "__main__":
    unittest.main()
