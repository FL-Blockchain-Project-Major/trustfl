"""
Strongly typed identifiers for the TrustFL protocol.

Identifiers provide prefix-based formatting and validation for all core domain entities:
- FederationId: fed_<hex/uuid>
- RoundId: rnd_<hex/uuid>
- ClientId: cli_<hex/uuid/address>
- ModelVersionId: mod_<hex/uuid/version>
- UpdateId: upd_<hex/uuid>
- ArtifactId: art_<hex/uuid>
"""

import re
from typing import Annotated

from trustfl_schemas.base import AfterValidator, BaseModel, Field


def _validate_prefix(value: str, prefix: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    pattern = rf"^{prefix}_[a-zA-Z0-9_\-\.]+$"
    if not re.match(pattern, value):
        raise ValueError(
            f"Invalid {name} format: '{value}'. Expected format: '{prefix}_<alphanumeric-identifier>'"
        )
    return value


def validate_federation_id(v: str) -> str:
    return _validate_prefix(v, "fed", "FederationId")


def validate_round_id(v: str) -> str:
    return _validate_prefix(v, "rnd", "RoundId")


def validate_client_id(v: str) -> str:
    return _validate_prefix(v, "cli", "ClientId")


def validate_model_version_id(v: str) -> str:
    return _validate_prefix(v, "mod", "ModelVersionId")


def validate_update_id(v: str) -> str:
    return _validate_prefix(v, "upd", "UpdateId")


def validate_artifact_id(v: str) -> str:
    return _validate_prefix(v, "art", "ArtifactId")


FederationId = Annotated[
    str,
    AfterValidator(validate_federation_id),
    Field(
        description="Unique identifier for a federation (format: 'fed_<id>')",
        examples=["fed_global_vision_01"],
    ),
]

RoundId = Annotated[
    str,
    AfterValidator(validate_round_id),
    Field(
        description="Unique identifier for a training round (format: 'rnd_<id>')",
        examples=["rnd_round_0001"],
    ),
]

ClientId = Annotated[
    str,
    AfterValidator(validate_client_id),
    Field(
        description="Unique identifier for a client node (format: 'cli_<id>')",
        examples=["cli_node_alpha_01"],
    ),
]

ModelVersionId = Annotated[
    str,
    AfterValidator(validate_model_version_id),
    Field(
        description="Unique identifier for a global/local model version (format: 'mod_<id>')",
        examples=["mod_resnet50_v1"],
    ),
]

UpdateId = Annotated[
    str,
    AfterValidator(validate_update_id),
    Field(
        description="Unique identifier for a client update submission (format: 'upd_<id>')",
        examples=["upd_round1_cli1"],
    ),
]

ArtifactId = Annotated[
    str,
    AfterValidator(validate_artifact_id),
    Field(
        description="Unique identifier for a stored model artifact (format: 'art_<id>')",
        examples=["art_checkpoint_001"],
    ),
]


class EntityIdentifierPayload(BaseModel):
    """Container helper for entity identifiers."""

    federation_id: FederationId
    round_id: RoundId
    client_id: ClientId
    model_version_id: ModelVersionId
    update_id: UpdateId
    artifact_id: ArtifactId
