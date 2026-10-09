"""
TrustFL cryptographic key management.

Algorithm: Ed25519 (RFC 8032)
  - 256-bit security level
  - 64-byte signatures
  - Deterministic (no per-signature randomness required)
  - Immune to timing side-channels by construction

Key storage rules:
  - Private keys NEVER go in Git (enforced by .gitignore *.pem, *.key)
  - Public keys are safe to publish; stored in coordinator key-registry
  - Keys are serialised as PEM for interoperability

Key files recommended layout (NOT in the repo):
  ~/.trustfl/keys/<client_id>/private.pem
  ~/.trustfl/keys/<client_id>/public.pem
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _priv_to_pem(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _pub_to_pem(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _pub_to_raw(public_key: Ed25519PublicKey) -> bytes:
    """32-byte raw public key (compact representation for wire protocol)."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _pub_from_raw(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def _pub_to_b64(public_key: Ed25519PublicKey) -> str:
    return base64.b64encode(_pub_to_raw(public_key)).decode()


def _pub_from_b64(b64: str) -> Ed25519PublicKey:
    return _pub_from_raw(base64.b64decode(b64))


# ---------------------------------------------------------------------------
# ClientIdentity — holds the key-pair for a single FL client
# ---------------------------------------------------------------------------


@dataclass
class ClientIdentity:
    """
    Cryptographic identity for a TrustFL client.

    The private key is always kept in memory and optionally persisted to
    a path outside the repository.  The public key is shared freely with
    the coordinator at registration time.
    """

    client_id: str
    _private_key: Ed25519PrivateKey
    _public_key: Ed25519PublicKey

    def __init__(self, client_id: str, private_key: Ed25519PrivateKey) -> None:
        self.client_id = client_id
        self._private_key = private_key
        self._public_key = private_key.public_key()

    # ------------------------------------------------------------------

    @classmethod
    def generate(cls, client_id: str) -> ClientIdentity:
        """Generate a fresh Ed25519 key-pair for client_id."""
        return cls(client_id, Ed25519PrivateKey.generate())

    @classmethod
    def load_pem(cls, client_id: str, pem_bytes: bytes) -> ClientIdentity:
        """Load from PKCS8 PEM-encoded private key bytes."""
        priv = serialization.load_pem_private_key(pem_bytes, password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            raise ValueError("Expected Ed25519 private key in PEM.")
        return cls(client_id, priv)

    @classmethod
    def load_or_generate(cls, client_id: str, key_path: Path | None = None) -> ClientIdentity:
        """
        Load existing key from key_path if present, otherwise generate and
        optionally save to key_path.  key_path must NOT be inside the repo.
        """
        if key_path and key_path.exists():
            return cls.load_pem(client_id, key_path.read_bytes())
        identity = cls.generate(client_id)
        if key_path:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(identity.private_key_pem)
            os.chmod(key_path, 0o600)
        return identity

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public_key

    @property
    def public_key_b64(self) -> str:
        """Base64-encoded 32-byte raw public key (sent to coordinator)."""
        return _pub_to_b64(self._public_key)

    @property
    def public_key_pem(self) -> bytes:
        return _pub_to_pem(self._public_key)

    @property
    def private_key_pem(self) -> bytes:
        return _priv_to_pem(self._private_key)

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def sign(self, message: bytes) -> bytes:
        """
        Sign message bytes with the Ed25519 private key.
        Returns a 64-byte signature.
        """
        return self._private_key.sign(message)

    def __repr__(self) -> str:
        return f"ClientIdentity(client_id={self.client_id!r}, pubkey={self.public_key_b64[:12]}...)"


# ---------------------------------------------------------------------------
# PublicKeyRegistry — coordinator-side store of client public keys
# ---------------------------------------------------------------------------


class PublicKeyRegistry:
    """
    Thread-safe in-memory registry mapping client_id → Ed25519PublicKey.
    The coordinator populates this at client registration time.
    """

    def __init__(self) -> None:
        import threading

        self._store: dict[str, Ed25519PublicKey] = {}
        self._lock = threading.Lock()

    def register(self, client_id: str, public_key_b64: str) -> None:
        """Register a client's public key (base64-encoded raw 32 bytes)."""
        key = _pub_from_b64(public_key_b64)
        with self._lock:
            self._store[client_id] = key

    def get(self, client_id: str) -> Ed25519PublicKey | None:
        with self._lock:
            return self._store.get(client_id)

    def is_registered(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._store

    def verify(self, client_id: str, message: bytes, signature: bytes) -> bool:
        """
        Verify that message was signed by client_id's registered key.
        Returns False (not raises) for any verification failure.
        """
        key = self.get(client_id)
        if key is None:
            return False
        try:
            key.verify(signature, message)
            return True
        except Exception:
            return False
