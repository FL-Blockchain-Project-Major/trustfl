"""
Canonical update metadata representation.

Every model update is bound to a signed metadata envelope that makes it
impossible to replay, redirect, or tamper with without detection.

Canonical form (for signing/hashing):
  JSON with sorted keys, no whitespace  →  UTF-8 bytes

Signed payload: SHA-256( canonical_bytes )
  Ed25519 operates on arbitrary-length messages, but we pre-hash to keep
  the signing interface consistent and to allow the hash to be logged
  independently of the signature.

UpdateMetadata fields
---------------------
federation_id   : globally unique federation identifier
round_id        : FL training round (1-based)
client_id       : the submitting client
model_version   : digest of the global model parameters used as input
update_id       : UUID-style unique identifier for this exact update
artifact_hash   : SHA-256 of the serialised parameter tensor ("sha256:<hex>")
timestamp       : Unix epoch seconds at signing time (±clock_skew_seconds accepted)
nonce           : <client_id>:<round_id>:<16 random hex bytes>  (replay guard)
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# UpdateMetadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UpdateMetadata:
    federation_id: str
    round_id: int
    client_id: str
    model_version: str
    update_id: str
    artifact_hash: str          # "sha256:<64 hex chars>"
    timestamp: int              # Unix epoch seconds
    nonce: str                  # replay-guard token

    # ------------------------------------------------------------------

    def canonical_bytes(self) -> bytes:
        """
        Deterministic JSON serialisation for signing.

        Rules:
          - all keys sorted alphabetically
          - no extra whitespace
          - UTF-8 encoding
        """
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def canonical_hash(self) -> bytes:
        """SHA-256 of canonical_bytes (32 bytes)."""
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_hash_hex(self) -> str:
        return self.canonical_hash().hex()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UpdateMetadata:
        return cls(
            federation_id=d["federation_id"],
            round_id=int(d["round_id"]),
            client_id=d["client_id"],
            model_version=d["model_version"],
            update_id=d["update_id"],
            artifact_hash=d["artifact_hash"],
            timestamp=int(d["timestamp"]),
            nonce=d["nonce"],
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def generate_nonce(client_id: str, round_id: int) -> str:
    """
    Nonce format: <client_id>:<round_id>:<16 random hex bytes>

    Encodes the client and round directly so the verifier can validate
    nonce structure without a separate lookup.
    """
    random_part = secrets.token_hex(16)
    return f"{client_id}:{round_id}:{random_part}"


def canonical_artifact_bytes(
    parameters: list,
    num_examples: int,
    metrics: dict[str, float],
) -> bytes:
    """Return the canonical bytes persisted for a signed update artifact."""
    return json.dumps(
        {
            "metrics": metrics,
            "num_examples": num_examples,
            "parameters": parameters,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def hash_artifact(
    parameters: list,
    num_examples: int,
    metrics: dict[str, float],
) -> str:
    """Hash the exact canonical artifact payload used by storage."""
    digest = hashlib.sha256(
        canonical_artifact_bytes(parameters, num_examples, metrics)
    ).hexdigest()
    return f"sha256:{digest}"


def hash_parameters(parameters: list) -> str:
    """
    Compute a stable SHA-256 hash of model parameters.

    Parameters is a list of lists of floats.
    Returns "sha256:<hex>".
    """
    raw = json.dumps(parameters, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}"


def build_metadata(
    *,
    federation_id: str,
    round_id: int,
    client_id: str,
    model_version: str,
    update_id: str,
    parameters: list,
    num_examples: int | None = None,
    metrics: dict[str, float] | None = None,
    timestamp: int | None = None,
) -> UpdateMetadata:
    """
    Construct a fresh UpdateMetadata for signing.

    artifact_hash and nonce are generated automatically.
    """
    return UpdateMetadata(
        federation_id=federation_id,
        round_id=round_id,
        client_id=client_id,
        model_version=model_version,
        update_id=update_id,
        # An update envelope must commit to every value that affects FedAvg.
        # There is deliberately no parameter-only compatibility envelope.
        artifact_hash=hash_artifact(parameters, num_examples or 0, metrics or {}),
        timestamp=timestamp if timestamp is not None else int(time.time()),
        nonce=generate_nonce(client_id, round_id),
    )
