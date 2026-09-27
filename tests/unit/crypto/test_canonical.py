"""Unit tests for canonical update metadata."""
from __future__ import annotations

import json
import time
import unittest

from trustfl_crypto.canonical import (
    UpdateMetadata,
    build_metadata,
    generate_nonce,
    hash_parameters,
)


PARAMS = [[0.1, 0.2, 0.3], [0.9]]


class TestUpdateMetadata(unittest.TestCase):

    def _make(self, **overrides) -> UpdateMetadata:
        defaults = dict(
            federation_id="fed-001",
            round_id=1,
            client_id="c1",
            model_version="sha256:aabbcc",
            update_id="update-001",
            artifact_hash=hash_parameters(PARAMS),
            timestamp=int(time.time()),
            nonce=generate_nonce("c1", 1),
        )
        defaults.update(overrides)
        return UpdateMetadata(**defaults)

    # ------------------------------------------------------------------
    # Canonical bytes

    def test_canonical_bytes_are_valid_json(self):
        meta = self._make()
        raw = meta.canonical_bytes()
        parsed = json.loads(raw)
        self.assertEqual(parsed["federation_id"], "fed-001")

    def test_canonical_bytes_keys_are_sorted(self):
        meta = self._make()
        raw = meta.canonical_bytes().decode()
        # Find positions of a few keys; they must be in alphabetical order
        pos_artifact = raw.index('"artifact_hash"')
        pos_client = raw.index('"client_id"')
        pos_federation = raw.index('"federation_id"')
        pos_nonce = raw.index('"nonce"')
        pos_round = raw.index('"round_id"')
        self.assertLess(pos_artifact, pos_client)
        self.assertLess(pos_client, pos_federation)
        self.assertLess(pos_federation, pos_nonce)
        self.assertLess(pos_nonce, pos_round)

    def test_canonical_bytes_no_whitespace(self):
        meta = self._make()
        raw = meta.canonical_bytes().decode()
        self.assertNotIn(" ", raw)
        self.assertNotIn("\n", raw)

    def test_canonical_bytes_deterministic(self):
        meta = self._make()
        self.assertEqual(meta.canonical_bytes(), meta.canonical_bytes())

    def test_different_metadata_different_bytes(self):
        m1 = self._make(round_id=1)
        m2 = self._make(round_id=2)
        self.assertNotEqual(m1.canonical_bytes(), m2.canonical_bytes())

    # ------------------------------------------------------------------
    # Hash

    def test_canonical_hash_is_32_bytes(self):
        meta = self._make()
        self.assertEqual(len(meta.canonical_hash()), 32)

    def test_canonical_hash_hex_is_64_chars(self):
        meta = self._make()
        self.assertEqual(len(meta.canonical_hash_hex()), 64)

    def test_hash_changes_when_payload_changes(self):
        m1 = self._make(round_id=1)
        m2 = self._make(round_id=2)
        self.assertNotEqual(m1.canonical_hash(), m2.canonical_hash())

    # ------------------------------------------------------------------
    # Serialisation roundtrip

    def test_to_dict_from_dict_roundtrip(self):
        meta = self._make()
        restored = UpdateMetadata.from_dict(meta.to_dict())
        self.assertEqual(meta, restored)

    def test_from_dict_with_extra_keys_ignores_them(self):
        """from_dict only reads known fields; extra keys are silently ignored."""
        meta = self._make()
        d = meta.to_dict()
        d["unexpected_field"] = "should_be_ignored"
        restored = UpdateMetadata.from_dict(d)
        self.assertEqual(restored, meta)


class TestHashParameters(unittest.TestCase):

    def test_returns_sha256_prefix(self):
        result = hash_parameters(PARAMS)
        self.assertTrue(result.startswith("sha256:"))

    def test_hash_is_64_hex_chars(self):
        h = hash_parameters(PARAMS)
        self.assertEqual(len(h), len("sha256:") + 64)

    def test_deterministic(self):
        self.assertEqual(hash_parameters(PARAMS), hash_parameters(PARAMS))

    def test_different_params_different_hash(self):
        p1 = [[0.1, 0.2]]
        p2 = [[0.1, 0.3]]
        self.assertNotEqual(hash_parameters(p1), hash_parameters(p2))

    def test_empty_params(self):
        result = hash_parameters([])
        self.assertTrue(result.startswith("sha256:"))


class TestGenerateNonce(unittest.TestCase):

    def test_nonce_format(self):
        nonce = generate_nonce("c1", 3)
        parts = nonce.split(":")
        self.assertEqual(parts[0], "c1")
        self.assertEqual(parts[1], "3")
        self.assertTrue(len(parts[2]) >= 16)

    def test_nonces_are_unique(self):
        nonces = {generate_nonce("c1", 1) for _ in range(100)}
        self.assertEqual(len(nonces), 100)


class TestBuildMetadata(unittest.TestCase):

    def test_build_metadata_fills_all_fields(self):
        meta = build_metadata(
            federation_id="fed-001",
            round_id=1,
            client_id="c1",
            model_version="sha256:xyz",
            update_id="u-001",
            parameters=PARAMS,
        )
        self.assertEqual(meta.federation_id, "fed-001")
        self.assertEqual(meta.round_id, 1)
        self.assertEqual(meta.client_id, "c1")
        self.assertTrue(meta.artifact_hash.startswith("sha256:"))
        self.assertIn("c1", meta.nonce)
        self.assertGreater(meta.timestamp, 0)

    def test_build_metadata_artifact_hash_matches_params(self):
        meta = build_metadata(
            federation_id="f",
            round_id=2,
            client_id="c",
            model_version="v",
            update_id="u",
            parameters=PARAMS,
        )
        self.assertEqual(meta.artifact_hash, hash_parameters(PARAMS))


if __name__ == "__main__":
    unittest.main()
