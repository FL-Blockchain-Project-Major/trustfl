"""
Unit tests for TrustFL typed models, serialization, and validation.
"""

import unittest

from trustfl_schemas.models import (
    BlockchainEventType,
    BlockchainRecord,
    ClientIdentity,
    ClientRole,
    ClientStatus,
    ClientUpdate,
    EvaluationMetrics,
    ModelArtifact,
    ProofMetadata,
    ProofType,
    StorageProtocol,
    TrainingMetrics,
)


class TestModels(unittest.TestCase):
    def test_client_identity_validation_and_serialization(self) -> None:
        client = ClientIdentity(
            client_id="cli_hospital_01",
            federation_id="fed_health_01",
            ethereum_address="0x71C8364720A550c389827AC539718475277FEe0C",
            public_key_hex="04" + "a" * 128,
            role=ClientRole.TRAINER,
            status=ClientStatus.ACTIVE,
            staked_amount_wei=1000000000000000000,
        )
        self.assertEqual(client.client_id, "cli_hospital_01")
        self.assertEqual(client.role, ClientRole.TRAINER)

        # JSON serialization roundtrip
        json_data = client.model_dump_json()
        loaded = ClientIdentity.model_validate_json(json_data)
        self.assertEqual(loaded.client_id, client.client_id)
        self.assertEqual(loaded.ethereum_address, client.ethereum_address)

        # Invalid Ethereum address
        with self.assertRaises(ValueError):
            ClientIdentity(
                client_id="cli_01",
                federation_id="fed_01",
                ethereum_address="not-an-eth-address",
                public_key_hex="04" + "a" * 128,
            )

    def test_model_artifact_hash_validation(self) -> None:
        valid_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        artifact = ModelArtifact(
            artifact_id="art_global_v1",
            storage_protocol=StorageProtocol.IPFS,
            uri="ipfs://bafybeicg2gg3p5k2w3",
            sha256_hash=valid_sha,
            size_bytes=1048576,
            content_format="safetensors",
        )
        self.assertEqual(artifact.sha256_hash, valid_sha)

        # Invalid hash length
        with self.assertRaises(ValueError):
            ModelArtifact(
                artifact_id="art_01",
                uri="ipfs://test",
                sha256_hash="tooshort",
                size_bytes=100,
            )

    def test_client_update_and_metrics_roundtrip(self) -> None:
        valid_sha = "a" * 64
        artifact = ModelArtifact(
            artifact_id="art_client_01",
            storage_protocol=StorageProtocol.IPFS,
            uri="ipfs://bafybeidemo",
            sha256_hash=valid_sha,
            size_bytes=524288,
        )
        metrics = TrainingMetrics(
            round_id="rnd_0001",
            client_id="cli_01",
            epochs_completed=5,
            samples_trained=1200,
            batch_size=32,
            learning_rate_used=0.001,
            final_loss=0.345,
            loss_history=[0.8, 0.6, 0.45, 0.38, 0.345],
            training_duration_seconds=42.5,
        )
        proof = ProofMetadata(
            proof_id="prf_zk_01",
            proof_type=ProofType.GROTH16,
            circuit_name="gradient_bounds",
            circuit_version="1.0.0",
            public_inputs_hash="b" * 64,
            proof_data_hex="0xdeadbeef" * 8,
            verified=True,
        )
        update = ClientUpdate(
            update_id="upd_rnd1_cli1",
            round_id="rnd_0001",
            client_id="cli_01",
            base_model_version_id="mod_v1",
            artifact=artifact,
            training_metrics=metrics,
            proof_metadata=proof,
            client_signature="c" * 128,
        )
        json_str = update.model_dump_json()
        restored = ClientUpdate.model_validate_json(json_str)
        self.assertEqual(restored.update_id, "upd_rnd1_cli1")
        self.assertEqual(restored.training_metrics.epochs_completed, 5)
        self.assertTrue(restored.proof_metadata.verified)

    def test_blockchain_record_validation(self) -> None:
        tx_hash = "0x" + "1" * 64
        record = BlockchainRecord(
            transaction_hash=tx_hash,
            block_number=1234567,
            contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
            event_type=BlockchainEventType.ROUND_INITIATED,
            round_id="rnd_0001",
            data_payload_hash="d" * 64,
        )
        self.assertEqual(record.transaction_hash, tx_hash)

        # Invalid transaction hash format
        with self.assertRaises(ValueError):
            BlockchainRecord(
                transaction_hash="invalid_tx_hash",
                block_number=1,
                contract_address="0x123",
                event_type=BlockchainEventType.ROUND_INITIATED,
                round_id="rnd_1",
                data_payload_hash="d" * 64,
            )

    def test_evaluation_metrics_constraints(self) -> None:
        eval_metrics = EvaluationMetrics(
            round_id="rnd_0001",
            loss=0.25,
            accuracy=0.945,
            f1_score=0.932,
            samples_evaluated=500,
        )
        self.assertEqual(eval_metrics.accuracy, 0.945)

        # Accuracy > 1.0 constraint violation
        with self.assertRaises(ValueError):
            EvaluationMetrics(
                round_id="rnd_0001",
                loss=0.1,
                accuracy=1.5,
                samples_evaluated=100,
            )


if __name__ == "__main__":
    unittest.main()
