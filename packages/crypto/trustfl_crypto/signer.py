"""
Update signer — client-side.

A client calls sign_update() to produce a SignedUpdate that bundles
the original update payload with a cryptographic proof of authenticity.

The signature covers SHA-256(canonical_bytes(metadata)), not the raw
parameters, because:
  1. Parameters can be large; hashing them first keeps signing fast.
  2. artifact_hash inside the metadata already commits to the parameters.
  3. The canonical hash can be logged in an audit trail independently.
"""
from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from typing import Any

from .canonical import UpdateMetadata, build_metadata
from .keys import ClientIdentity

# ---------------------------------------------------------------------------
# SignedUpdate — the wire object sent from client to coordinator
# ---------------------------------------------------------------------------

@dataclass
class SignedUpdate:
    """
    Encapsulates a model update together with its proof of authenticity.

    Wire format (JSON-serialisable dict):
      {
        "metadata": { ...UpdateMetadata fields... },
        "signature": "<base64-encoded 64-byte Ed25519 signature>",
        "parameters": [[...], ...],
        "num_examples": 42,
        "metrics": { "loss": 0.3 }
      }

    The signature covers SHA-256(canonical_bytes(metadata)).
    """

    metadata: UpdateMetadata
    signature: bytes                 # 64-byte Ed25519 sig
    parameters: list[list[float]]
    num_examples: int
    metrics: dict[str, float]

    # ------------------------------------------------------------------

    @property
    def signature_b64(self) -> str:
        return base64.b64encode(self.signature).decode()

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "signature": self.signature_b64,
            "parameters": self.parameters,
            "num_examples": self.num_examples,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignedUpdate:
        return cls(
            metadata=UpdateMetadata.from_dict(d["metadata"]),
            signature=base64.b64decode(d["signature"]),
            parameters=d["parameters"],
            num_examples=int(d["num_examples"]),
            metrics={k: float(v) for k, v in d.get("metrics", {}).items()},
        )


# ---------------------------------------------------------------------------
# Signer
# ---------------------------------------------------------------------------

class UpdateSigner:
    """
    Creates a SignedUpdate from raw training output.

    Usage::

        signer = UpdateSigner(identity, federation_id="fed-001")
        signed = signer.sign(
            round_id=1,
            model_version="sha256:abc...",
            parameters=[[0.1, 0.2], [0.9]],
            num_examples=50,
            metrics={"loss": 0.32},
        )
    """

    def __init__(self, identity: ClientIdentity, federation_id: str) -> None:
        self.identity = identity
        self.federation_id = federation_id

    def sign(
        self,
        *,
        round_id: int,
        model_version: str,
        parameters: list[list[float]],
        num_examples: int,
        metrics: dict[str, float],
        update_id: str | None = None,
    ) -> SignedUpdate:
        """
        Build UpdateMetadata, sign its canonical hash, return a SignedUpdate.
        """
        if update_id is None:
            update_id = str(uuid.uuid4())

        metadata = build_metadata(
            federation_id=self.federation_id,
            round_id=round_id,
            client_id=self.identity.client_id,
            model_version=model_version,
            update_id=update_id,
            parameters=parameters,
            num_examples=num_examples,
            metrics=metrics,
        )

        # Sign the canonical hash (32 bytes) — deterministic, fast
        message_to_sign = metadata.canonical_bytes()
        signature = self.identity.sign(message_to_sign)

        return SignedUpdate(
            metadata=metadata,
            signature=signature,
            parameters=parameters,
            num_examples=num_examples,
            metrics=metrics,
        )
