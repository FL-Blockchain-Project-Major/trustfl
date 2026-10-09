"""
TrustFL Cryptographic Package — Public API.

Algorithm: Ed25519 (RFC 8032, FIPS 186-5 compatible)
  - 256-bit security
  - 64-byte deterministic signatures
  - 32-byte public keys (wire: base64 ~ 44 chars)
  - Provided by: cryptography >= 2.6

Signing flow (client):
  1. ClientIdentity.generate(client_id)        # or load from PEM
  2. UpdateSigner(identity, federation_id)
  3. signer.sign(round_id, model_version, parameters, ...)
     → SignedUpdate (metadata + 64-byte signature + parameters)
  4. Send SignedUpdate.to_dict() as JSON to coordinator

Verification flow (coordinator):
  1. PublicKeyRegistry.register(client_id, public_key_b64)
  2. UpdateVerifier(registry)
  3. verifier.set_round(current_round, accepted_model_versions)
  4. verifier.verify(signed_update, expected_client_id)
     → VerificationResult(.ok / .status / .detail)
"""

from .canonical import (
    UpdateMetadata,
    build_metadata,
    canonical_artifact_bytes,
    generate_nonce,
    hash_artifact,
    hash_parameters,
)
from .keys import ClientIdentity, PublicKeyRegistry
from .signer import SignedUpdate, UpdateSigner
from .verifier import (
    NonceStore,
    UpdateVerifier,
    VerificationResult,
    VerificationStatus,
)

__all__ = [
    # canonical
    "UpdateMetadata",
    "build_metadata",
    "canonical_artifact_bytes",
    "hash_artifact",
    "generate_nonce",
    "hash_parameters",
    # keys
    "ClientIdentity",
    "PublicKeyRegistry",
    # signer
    "SignedUpdate",
    "UpdateSigner",
    # verifier
    "NonceStore",
    "UpdateVerifier",
    "VerificationResult",
    "VerificationStatus",
]
