"""
Domain models and typed schemas for the TrustFL protocol.

Schemas defined:
- ClientIdentity: Public key, address, role, status, metadata
- ProofMetadata: Zero-knowledge proof verification metadata
- ModelArtifact: Verifiable storage descriptor (IPFS CID, Merkle root, format)
- ModelMetadata: Architecture, parameter count, framework, hyperparameters
- TrainingMetrics: Epochs, loss, duration, resource usage
- EvaluationMetrics: Accuracy, f1, precision, recall, loss
- ClientUpdate: Signed client update containing artifact reference & ZK proof
- BlockchainRecord: On-chain transaction reference & event log details
- TrainingRound: Full lifecycle state machine for a federated round
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
import re
from trustfl_schemas.base import BaseModel, ConfigDict, Field, field_validator

from trustfl_schemas.identifiers import (
    ArtifactId,
    ClientId,
    FederationId,
    ModelVersionId,
    RoundId,
    UpdateId,
)
from trustfl_schemas.lifecycle import RoundState, assert_valid_transition


class ClientRole(str, Enum):
    TRAINER = "TRAINER"
    EVALUATOR = "EVALUATOR"
    AGGREGATOR = "AGGREGATOR"


class ClientStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    OFFLINE = "OFFLINE"
    SLASHED = "SLASHED"


class ClientIdentity(BaseModel):
    """
    Cryptographic identity and registration profile for a participating client node.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: ClientId
    federation_id: FederationId
    ethereum_address: str = Field(
        ...,
        description="Checksummed EVM account address used for on-chain identity and staking",
        examples=["0x71C8364720A550c389827AC539718475277FEe0C"],
    )
    public_key_hex: str = Field(
        ...,
        description="Hex-encoded public key (secp256k1 or Ed25519) used for payload signature verification",
        min_length=64,
    )
    role: ClientRole = Field(default=ClientRole.TRAINER)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of client registration in UTC",
    )
    staked_amount_wei: int = Field(
        default=0,
        ge=0,
        description="Staked balance recorded on the smart contract in wei",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary hardware, geographic, or node telemetry metadata",
    )

    @field_validator("ethereum_address")
    @classmethod
    def validate_eth_address(cls, v: str) -> str:
        if not re.match(r"^0x[a-fA-F0-9]{40}$", v):
            raise ValueError(f"Invalid Ethereum address format: '{v}'")
        return v


class ProofType(str, Enum):
    GROTH16 = "GROTH16"
    PLONK = "PLONK"
    STARK = "STARK"
    NOIR = "NOIR"


class ProofMetadata(BaseModel):
    """
    Metadata describing a zero-knowledge proof of training integrity and boundary bounds.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    proof_id: str = Field(..., description="Unique proof identifier")
    proof_type: ProofType = Field(default=ProofType.GROTH16)
    circuit_name: str = Field(..., description="Identifier of the circuit used")
    circuit_version: str = Field(..., description="Semantic version of the circuit definition")
    public_inputs_hash: str = Field(
        ...,
        description="SHA-256 or Poseidon commitment hash of the public inputs",
        min_length=64,
    )
    proof_data_hex: str = Field(
        ...,
        description="Hex-encoded proof points (e.g. A, B, C for Groth16)",
    )
    verified: bool = Field(
        default=False,
        description="Boolean indicating whether proof verification succeeded",
    )
    verification_timestamp: datetime | None = None


class StorageProtocol(str, Enum):
    IPFS = "ipfs"
    S3 = "s3"
    LOCAL_MOCK = "local"


class ModelArtifact(BaseModel):
    """
    Cryptographically verifiable storage locator for serialized model weights or weight updates.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: ArtifactId
    storage_protocol: StorageProtocol = Field(default=StorageProtocol.IPFS)
    uri: str = Field(
        ...,
        description="Uniform resource identifier (e.g. 'ipfs://bafy...', 's3://bucket/key')",
    )
    sha256_hash: str = Field(
        ...,
        description="Cryptographic SHA-256 hash of the raw model artifact bytes",
        min_length=64,
        max_length=64,
    )
    size_bytes: int = Field(..., gt=0, description="Size in bytes of the artifact")
    merkle_root: str | None = Field(
        default=None,
        description="Merkle tree root over tensor parameter chunks if applicable",
    )
    content_format: str = Field(
        default="safetensors",
        description="Serialization format (e.g., safetensors, onnx, state_dict)",
    )

    @field_validator("sha256_hash")
    @classmethod
    def validate_hash_format(cls, v: str) -> str:
        if not re.match(r"^[a-fA-F0-9]{64}$", v):
            raise ValueError(f"sha256_hash must be a 64-character hexadecimal string, got '{v}'")
        return v.lower()


class ModelMetadata(BaseModel):
    """
    Detailed model architecture, framework specifications, and hyperparameter configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version_id: ModelVersionId
    federation_id: FederationId
    model_name: str
    architecture_family: str = Field(..., examples=["resnet50", "transformer", "mlp"])
    framework: str = Field(default="pytorch", examples=["pytorch", "tensorflow", "jax"])
    parameter_count: int = Field(..., gt=0)
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TrainingMetrics(BaseModel):
    """
    Performance and operational telemetry from a local training execution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_id: RoundId
    client_id: ClientId
    epochs_completed: int = Field(..., ge=1)
    samples_trained: int = Field(..., ge=1)
    batch_size: int = Field(..., ge=1)
    learning_rate_used: float = Field(..., gt=0.0)
    final_loss: float = Field(...)
    loss_history: list[float] = Field(default_factory=list)
    training_duration_seconds: float = Field(..., ge=0.0)
    compute_device: str = Field(default="cpu", examples=["cuda:0", "cpu", "mps"])


class EvaluationMetrics(BaseModel):
    """
    Evaluation telemetry computed over test or validation subsets.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_id: RoundId
    evaluator_client_id: ClientId | None = None
    loss: float
    accuracy: float = Field(..., ge=0.0, le=1.0)
    f1_score: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    samples_evaluated: int = Field(..., ge=1)
    custom_metrics: dict[str, float] = Field(default_factory=dict)


class ClientUpdate(BaseModel):
    """
    Signed update submitted by a client node at the conclusion of local training.
    Contains model artifact locator, metrics, and zero-knowledge proof commitment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    update_id: UpdateId
    round_id: RoundId
    client_id: ClientId
    base_model_version_id: ModelVersionId
    artifact: ModelArtifact
    training_metrics: TrainingMetrics
    proof_metadata: ProofMetadata | None = None
    client_signature: str = Field(
        ...,
        description="Hex-encoded signature over (round_id + client_id + artifact.sha256_hash + proof_hash)",
        min_length=64,
    )
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BlockchainEventType(str, Enum):
    ROUND_INITIATED = "ROUND_INITIATED"
    CLIENT_COMMITTED = "CLIENT_COMMITTED"
    UPDATE_ACCEPTED = "UPDATE_ACCEPTED"
    MODEL_AGGREGATED = "MODEL_AGGREGATED"
    ROUND_CONCLUDED = "ROUND_CONCLUDED"
    CLIENT_SLASHED = "CLIENT_SLASHED"


class BlockchainRecord(BaseModel):
    """
    On-chain transaction receipt and event log tracking auditability on the smart contract layer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_hash: str = Field(
        ...,
        description="EVM transaction hash in 0x-prefixed hex format",
        min_length=66,
        max_length=66,
    )
    block_number: int = Field(..., ge=0)
    contract_address: str = Field(
        ...,
        description="Target contract address (e.g. ModelRegistry or RoundAuditor)",
    )
    event_type: BlockchainEventType
    round_id: RoundId
    client_id: ClientId | None = None
    model_version_id: ModelVersionId | None = None
    data_payload_hash: str = Field(
        ...,
        description="Hash of the state payload committed to blockchain calldata or storage",
        min_length=64,
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("transaction_hash")
    @classmethod
    def validate_tx_hash(cls, v: str) -> str:
        if not re.match(r"^0x[a-fA-F0-9]{64}$", v):
            raise ValueError(f"transaction_hash must be a 66-character '0x' prefixed hex string, got '{v}'")
        return v


class TrainingRound(BaseModel):
    """
    Top-level federated learning round entity.
    Tracks state machine progression, participants, submitted updates, aggregated model, and audit trail.
    """

    model_config = ConfigDict(extra="forbid")

    round_id: RoundId
    federation_id: FederationId
    round_number: int = Field(..., ge=0)
    state: RoundState = Field(default=RoundState.ROUND_CREATED)
    base_model_version_id: ModelVersionId
    target_model_version_id: ModelVersionId | None = None
    min_clients: int = Field(default=3, ge=1)
    max_clients: int = Field(default=10, ge=1)
    assigned_client_ids: list[ClientId] = Field(default_factory=list)
    submitted_update_ids: list[UpdateId] = Field(default_factory=list)
    verified_update_ids: list[UpdateId] = Field(default_factory=list)
    aggregated_artifact: ModelArtifact | None = None
    evaluation_metrics: EvaluationMetrics | None = None
    blockchain_records: list[BlockchainRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, new_state: RoundState) -> None:
        """
        Transition the round to a new state after verifying validity in the state machine.
        """
        assert_valid_transition(self.state, new_state)
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)
