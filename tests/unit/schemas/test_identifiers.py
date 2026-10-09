"""
Unit tests for TrustFL typed identifiers.
"""

import unittest

from trustfl_schemas.identifiers import (
    EntityIdentifierPayload,
    validate_artifact_id,
    validate_client_id,
    validate_federation_id,
    validate_model_version_id,
    validate_round_id,
    validate_update_id,
)


class TestIdentifiers(unittest.TestCase):
    def test_valid_identifiers(self) -> None:
        self.assertEqual(
            validate_federation_id("fed_cancer_detection_01"), "fed_cancer_detection_01"
        )
        self.assertEqual(validate_round_id("rnd_0001"), "rnd_0001")
        self.assertEqual(validate_client_id("cli_hospital_alpha"), "cli_hospital_alpha")
        self.assertEqual(validate_model_version_id("mod_resnet18_v1"), "mod_resnet18_v1")
        self.assertEqual(validate_update_id("upd_round1_cli1"), "upd_round1_cli1")
        self.assertEqual(validate_artifact_id("art_checkpoint_001"), "art_checkpoint_001")

    def test_invalid_identifiers_raise_value_error(self) -> None:
        invalid_cases = [
            (validate_federation_id, "invalid_prefix_01"),
            (validate_federation_id, "fed_"),  # empty body
            (validate_round_id, "round_0001"),
            (validate_client_id, "node_0001"),
            (validate_model_version_id, "v1.0.0"),
            (validate_update_id, "update_123"),
            (validate_artifact_id, "artifact_123"),
            (validate_round_id, "rnd_invalid spaces"),
        ]
        for validator, value in invalid_cases:
            with self.subTest(validator=validator.__name__, value=value):
                with self.assertRaises(ValueError):
                    validator(value)

    def test_identifier_payload_model(self) -> None:
        payload = EntityIdentifierPayload(
            federation_id="fed_1",
            round_id="rnd_1",
            client_id="cli_1",
            model_version_id="mod_1",
            update_id="upd_1",
            artifact_id="art_1",
        )
        self.assertEqual(payload.federation_id, "fed_1")
        self.assertEqual(payload.round_id, "rnd_1")

        with self.assertRaises(ValueError):
            EntityIdentifierPayload(
                federation_id="wrong_prefix",
                round_id="rnd_1",
                client_id="cli_1",
                model_version_id="mod_1",
                update_id="upd_1",
                artifact_id="art_1",
            )


if __name__ == "__main__":
    unittest.main()
