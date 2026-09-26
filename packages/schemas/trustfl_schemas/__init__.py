"""
TrustFL Schemas Package.

Exports all shared identifiers, lifecycle states, and domain models for the TrustFL protocol.
"""

from trustfl_schemas.identifiers import (
    ArtifactId,
    ClientId,
    EntityIdentifierPayload,
    FederationId,
    ModelVersionId,
    RoundId,
    UpdateId,
    validate_artifact_id,
    validate_client_id,
    validate_federation_id,
    validate_model_version_id,
    validate_round_id,
    validate_update_id,
)
from trustfl_schemas.lifecycle import (
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    RoundState,
    assert_valid_transition,
)
from trustfl_schemas.models import (
    BlockchainEventType,
    BlockchainRecord,
    ClientIdentity,
    ClientRole,
    ClientStatus,
    ClientUpdate,
    EvaluationMetrics,
    ModelArtifact,
    ModelMetadata,
    ProofMetadata,
    ProofType,
    StorageProtocol,
    TrainingMetrics,
    TrainingRound,
)

__all__ = [
    # Identifiers
    "FederationId",
    "RoundId",
    "ClientId",
    "ModelVersionId",
    "UpdateId",
    "ArtifactId",
    "EntityIdentifierPayload",
    "validate_federation_id",
    "validate_round_id",
    "validate_client_id",
    "validate_model_version_id",
    "validate_update_id",
    "validate_artifact_id",
    # Lifecycle
    "RoundState",
    "VALID_TRANSITIONS",
    "InvalidStateTransitionError",
    "assert_valid_transition",
    # Domain Models
    "ClientIdentity",
    "ClientRole",
    "ClientStatus",
    "ProofMetadata",
    "ProofType",
    "StorageProtocol",
    "ModelArtifact",
    "ModelMetadata",
    "TrainingMetrics",
    "EvaluationMetrics",
    "ClientUpdate",
    "BlockchainEventType",
    "BlockchainRecord",
    "TrainingRound",
]
