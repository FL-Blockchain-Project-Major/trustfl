"""Unit tests for cryptographic key management."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from trustfl_crypto.keys import ClientIdentity, PublicKeyRegistry


class TestClientIdentity(unittest.TestCase):
    def test_generate_produces_unique_keys(self):
        id1 = ClientIdentity.generate("c1")
        id2 = ClientIdentity.generate("c1")
        # Two freshly generated keys must differ
        self.assertNotEqual(id1.public_key_b64, id2.public_key_b64)

    def test_public_key_b64_is_44_chars(self):
        identity = ClientIdentity.generate("c1")
        # base64(32 bytes) = 44 chars (with padding)
        self.assertEqual(len(identity.public_key_b64), 44)

    def test_pem_roundtrip(self):
        identity = ClientIdentity.generate("c1")
        pem = identity.private_key_pem
        loaded = ClientIdentity.load_pem("c1", pem)
        self.assertEqual(identity.public_key_b64, loaded.public_key_b64)

    def test_load_or_generate_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "private.pem"
            ClientIdentity.load_or_generate("c1", path)
            self.assertTrue(path.exists())
            # File must be owner-readable only
            mode = oct(os.stat(path).st_mode)[-3:]
            self.assertEqual(mode[0], "6", "Owner should have rw; got " + mode)

    def test_load_or_generate_loads_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "private.pem"
            first = ClientIdentity.load_or_generate("c1", path)
            second = ClientIdentity.load_or_generate("c1", path)
            # Same key loaded twice → same public key
            self.assertEqual(first.public_key_b64, second.public_key_b64)

    def test_sign_produces_64_bytes(self):
        identity = ClientIdentity.generate("c1")
        sig = identity.sign(b"test message")
        self.assertEqual(len(sig), 64)

    def test_sign_is_deterministic_for_same_key_and_message(self):
        identity = ClientIdentity.generate("c1")
        msg = b"deterministic"
        # Ed25519 is deterministic
        self.assertEqual(identity.sign(msg), identity.sign(msg))

    def test_repr_does_not_leak_private_key(self):
        identity = ClientIdentity.generate("c1")
        r = repr(identity)
        # repr should not contain the full key
        self.assertNotIn(identity.private_key_pem.decode()[:20], r)
        self.assertIn("c1", r)


class TestPublicKeyRegistry(unittest.TestCase):
    def _make_pair(self, cid: str):
        identity = ClientIdentity.generate(cid)
        return identity, identity.public_key_b64

    def test_register_and_lookup(self):
        registry = PublicKeyRegistry()
        identity, pubkey_b64 = self._make_pair("c1")
        registry.register("c1", pubkey_b64)
        self.assertTrue(registry.is_registered("c1"))
        self.assertFalse(registry.is_registered("unknown"))

    def test_verify_valid_signature(self):
        registry = PublicKeyRegistry()
        identity, pubkey_b64 = self._make_pair("c1")
        registry.register("c1", pubkey_b64)
        msg = b"payload to sign"
        sig = identity.sign(msg)
        self.assertTrue(registry.verify("c1", msg, sig))

    def test_verify_wrong_message_fails(self):
        registry = PublicKeyRegistry()
        identity, pubkey_b64 = self._make_pair("c1")
        registry.register("c1", pubkey_b64)
        msg = b"original"
        sig = identity.sign(msg)
        self.assertFalse(registry.verify("c1", b"tampered", sig))

    def test_verify_wrong_client_fails(self):
        registry = PublicKeyRegistry()
        identity_a, pub_a = self._make_pair("a")
        identity_b, pub_b = self._make_pair("b")
        registry.register("a", pub_a)
        registry.register("b", pub_b)
        msg = b"message"
        sig_b = identity_b.sign(msg)
        # b's signature must not verify against a's key
        self.assertFalse(registry.verify("a", msg, sig_b))

    def test_verify_unknown_client_returns_false(self):
        registry = PublicKeyRegistry()
        self.assertFalse(registry.verify("nobody", b"msg", b"\x00" * 64))

    def test_verify_corrupted_signature_returns_false(self):
        registry = PublicKeyRegistry()
        identity, pub = self._make_pair("c1")
        registry.register("c1", pub)
        sig = bytearray(identity.sign(b"msg"))
        sig[0] ^= 0xFF  # flip first byte
        self.assertFalse(registry.verify("c1", b"msg", bytes(sig)))

    def test_register_overwrites_old_key(self):
        registry = PublicKeyRegistry()
        id1, pub1 = self._make_pair("c1")
        id2, pub2 = self._make_pair("c1")
        registry.register("c1", pub1)
        registry.register("c1", pub2)  # overwrites
        msg = b"hello"
        # Only id2's sig should verify now
        self.assertTrue(registry.verify("c1", msg, id2.sign(msg)))
        self.assertFalse(registry.verify("c1", msg, id1.sign(msg)))


if __name__ == "__main__":
    unittest.main()
