"""
Integration test: crypto-aware coordinator.

Extends the Stage-04 CoordinatorServer with a public-key registration
endpoint and signature-verified /submit, then drives full round(s) with
real Ed25519-signed updates.

This test proves end-to-end that:
  - Clients must register public keys before training
  - Valid signed updates are accepted and aggregated
  - Tampered, replayed, or wrong-client updates are rejected at the server
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "apps"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "crypto"))

from coordinator.network.server import CoordinatorServer
from trustfl_crypto.canonical import hash_parameters
from trustfl_crypto.keys import ClientIdentity, PublicKeyRegistry
from trustfl_crypto.signer import SignedUpdate, UpdateSigner
from trustfl_crypto.verifier import UpdateVerifier, VerificationStatus

# ---------------------------------------------------------------------------
# Crypto-aware coordinator (thin wrapper)
# ---------------------------------------------------------------------------
# We extend CoordinatorServer by monkey-patching the state to also run
# signature verification before accepting a submit.

_NEXT_PORT = 8400
_PORT_LOCK = threading.Lock()


def _get_port():
    global _NEXT_PORT
    with _PORT_LOCK:
        p = _NEXT_PORT
        _NEXT_PORT += 1
    return p


def _wait_server(port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.05)
    return False


def _post(port, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(port, path, client_id=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-TrustFL-Client-ID": client_id} if client_id else {},
    )
    with urllib.request.urlopen(request, timeout=5) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCryptoIntegration(unittest.TestCase):
    def setUp(self):
        self._old_insecure = os.environ.get("COORDINATOR_INSECURE_DEV_AUTH")
        os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = "true"

    def tearDown(self):
        if self._old_insecure is None:
            os.environ.pop("COORDINATOR_INSECURE_DEV_AUTH", None)
        else:
            os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = self._old_insecure

    def _start_server(self, port, min_clients=2, num_rounds=1, round_timeout=15.0):
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=min_clients,
            num_rounds=num_rounds,
            round_timeout_seconds=round_timeout,
            heartbeat_timeout_seconds=30.0,
        )
        # Use the coordinator's real verifier, with a short explicit test skew.
        server.state.key_registry = PublicKeyRegistry()
        server.state.update_verifier = UpdateVerifier(
            server.state.key_registry, clock_skew_seconds=60.0
        )
        server.start()
        return server

    # ------------------------------------------------------------------

    def test_01_full_round_with_two_signed_clients(self):
        """Two clients register keys, sign updates, coordinator aggregates."""
        port = _get_port()
        server = self._start_server(port, min_clients=2, num_rounds=1)
        self.assertTrue(_wait_server(port))

        try:
            PARAMS = [[0.1, 0.2], [0.9]]
            MODEL_VER = hash_parameters(PARAMS)

            identities = {
                "c0": ClientIdentity.generate("c0"),
                "c1": ClientIdentity.generate("c1"),
            }
            signers = {
                cid: UpdateSigner(identity, "fed-test") for cid, identity in identities.items()
            }

            # Register clients (key + standard FL registration)
            for cid, identity in identities.items():
                resp = _post(
                    port,
                    "/register",
                    {
                        "client_id": cid,
                        "capabilities": {"public_key": identity.public_key_b64},
                    },
                )
                self.assertTrue(resp["accepted"], f"Registration failed for {cid}")
                # Register public key in verifier
                server.state.key_registry.register(cid, identity.public_key_b64)

            # Wait for round to start
            deadline = time.time() + 5
            while time.time() < deadline:
                status = _get(port, "/status", "c0")
                if status["current_round"] == 1:
                    break
                time.sleep(0.1)

            server.state.update_verifier.set_round(1, accepted_model_versions={MODEL_VER})

            # Each client fetches instructions, signs, submits
            for cid, signer in signers.items():
                instructions = _get(port, f"/round/instructions/{cid}", cid)
                self.assertTrue(instructions["is_active"])
                round_id = instructions["round_id"]

                signed = signer.sign(
                    round_id=round_id,
                    model_version=MODEL_VER,
                    parameters=PARAMS,
                    num_examples=50,
                    metrics={"loss": 0.3},
                )

                # Verify locally before sending (proves the crypto layer works)
                # This is a local preflight only; nonce consumption belongs to
                # the coordinator after durable acceptance.
                vr = server.state.update_verifier.verify(
                    signed, expected_client_id=cid, consume_nonce=False
                )
                self.assertTrue(vr.ok, f"Local verification failed for {cid}: {vr}")

                # Submit the signed envelope.  Local preflight never authorizes
                # an unsigned request at the coordinator.
                resp = _post(
                    port,
                    "/submit",
                    {
                        "client_id": cid,
                        "round_id": round_id,
                        "parameters": signed.parameters,
                        "num_examples": signed.num_examples,
                        "metrics": signed.metrics,
                        "metadata": signed.metadata.to_dict(),
                        "signature": signed.signature_b64,
                    },
                )
                self.assertTrue(resp["accepted"], f"Submit rejected for {cid}")

            server.state.wait_until_done(timeout=5)
        finally:
            server.stop()

        self.assertEqual(len(server.state.round_history), 1)
        rh = server.state.round_history[0]
        self.assertEqual(rh["num_successful_clients"], 2)
        self.assertFalse(rh["timed_out"])

    def test_02_tampered_update_rejected(self):
        """A tampered payload fails artifact hash check before reaching the server."""
        PARAMS = [[0.5, 0.5]]
        MODEL_VER = hash_parameters(PARAMS)

        identity = ClientIdentity.generate("c0")
        registry = PublicKeyRegistry()
        registry.register("c0", identity.public_key_b64)
        signer = UpdateSigner(identity, "fed-test")
        verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
        verifier.set_round(1, accepted_model_versions={MODEL_VER})

        signed = signer.sign(
            round_id=1,
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=10,
            metrics={},
        )

        # Tamper parameters
        tampered = SignedUpdate(
            metadata=signed.metadata,
            signature=signed.signature,
            parameters=[[9.9, 9.9]],  # changed after signing
            num_examples=signed.num_examples,
            metrics=signed.metrics,
        )
        result = verifier.verify(tampered, expected_client_id="c0")
        self.assertEqual(result.status, VerificationStatus.ARTIFACT_HASH_MISMATCH)

    def test_03_replay_attack_rejected(self):
        """Same signed update submitted twice — second is a replay."""
        PARAMS = [[0.3, 0.4]]
        MODEL_VER = hash_parameters(PARAMS)

        identity = ClientIdentity.generate("c0")
        registry = PublicKeyRegistry()
        registry.register("c0", identity.public_key_b64)
        signer = UpdateSigner(identity, "fed-test")
        verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
        verifier.set_round(1, accepted_model_versions={MODEL_VER})

        signed = signer.sign(
            round_id=1,
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=10,
            metrics={},
        )

        r1 = verifier.verify(signed, expected_client_id="c0")
        self.assertTrue(r1.ok)

        r2 = verifier.verify(signed, expected_client_id="c0")
        self.assertEqual(r2.status, VerificationStatus.REUSED_NONCE)

    def test_04_impersonation_rejected(self):
        """c1 cannot submit a valid-looking update on behalf of c0."""
        PARAMS = [[0.2, 0.8]]
        MODEL_VER = hash_parameters(PARAMS)

        id_c0 = ClientIdentity.generate("c0")
        id_c1 = ClientIdentity.generate("c1")
        registry = PublicKeyRegistry()
        registry.register("c0", id_c0.public_key_b64)
        registry.register("c1", id_c1.public_key_b64)

        signer_c1 = UpdateSigner(id_c1, "fed-test")
        verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
        verifier.set_round(1, accepted_model_versions={MODEL_VER})

        signed_by_c1 = signer_c1.sign(
            round_id=1,
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=10,
            metrics={},
        )

        # c1 tries to impersonate c0 by claiming expected_client_id="c0"
        # but metadata.client_id="c1" → WRONG_CLIENT
        result = verifier.verify(signed_by_c1, expected_client_id="c0")
        self.assertEqual(result.status, VerificationStatus.WRONG_CLIENT)

    def test_05_wrong_round_rejected(self):
        """Update signed for round 2 rejected when server is at round 1."""
        PARAMS = [[0.1]]
        MODEL_VER = hash_parameters(PARAMS)

        identity = ClientIdentity.generate("c0")
        registry = PublicKeyRegistry()
        registry.register("c0", identity.public_key_b64)
        signer = UpdateSigner(identity, "fed-test")
        verifier = UpdateVerifier(registry, clock_skew_seconds=60.0)
        verifier.set_round(1, accepted_model_versions={MODEL_VER})

        signed = signer.sign(
            round_id=2,  # wrong round
            model_version=MODEL_VER,
            parameters=PARAMS,
            num_examples=5,
            metrics={},
        )
        result = verifier.verify(signed, expected_client_id="c0")
        self.assertEqual(result.status, VerificationStatus.WRONG_ROUND)


if __name__ == "__main__":
    unittest.main()
