"""
Update verifier — coordinator-side.

VerificationResult encodes exactly why a submission was accepted or
rejected so callers can log / return meaningful error messages.

Rejection matrix
----------------
INVALID_SIGNATURE     Ed25519 verification failed (wrong key or tampered payload)
UNKNOWN_CLIENT        client_id has no registered public key
REUSED_NONCE          nonce was seen before (replay attack)
WRONG_ROUND           metadata.round_id != current server round
WRONG_CLIENT          metadata.client_id != the cid in the HTTP request
ARTIFACT_HASH_MISMATCH artifact_hash in metadata ≠ hash(submitted parameters)
STALE_MODEL_VERSION   model_version not in the set of accepted versions
TIMESTAMP_DRIFT       |metadata.timestamp - now| > clock_skew_seconds
NONCE_MALFORMED       nonce does not follow <client>:<round>:<hex> format
OK                    all checks passed
"""
from __future__ import annotations

import enum
import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Set

from .canonical import UpdateMetadata, hash_parameters
from .keys import PublicKeyRegistry
from .signer import SignedUpdate


# ---------------------------------------------------------------------------
# Result enum
# ---------------------------------------------------------------------------

class VerificationStatus(enum.Enum):
    OK = "OK"
    UNKNOWN_CLIENT = "UNKNOWN_CLIENT"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    REUSED_NONCE = "REUSED_NONCE"
    WRONG_ROUND = "WRONG_ROUND"
    WRONG_CLIENT = "WRONG_CLIENT"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    STALE_MODEL_VERSION = "STALE_MODEL_VERSION"
    TIMESTAMP_DRIFT = "TIMESTAMP_DRIFT"
    NONCE_MALFORMED = "NONCE_MALFORMED"


@dataclass
class VerificationResult:
    status: VerificationStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == VerificationStatus.OK

    def __repr__(self) -> str:
        return f"VerificationResult({self.status.value}: {self.detail!r})"


_OK = VerificationResult(VerificationStatus.OK)


# ---------------------------------------------------------------------------
# Nonce store (thread-safe, round-scoped)
# ---------------------------------------------------------------------------

class NonceStore:
    """
    Tracks used nonces, scoped to active rounds.

    Design:
      - Each round gets its own set of seen nonces.
      - When the round advances, old sets are discarded (memory bounded).
      - Nonces from a future round are rejected (wrong_round catches first).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # round_id → set of nonce strings
        self._by_round: dict[int, Set[str]] = {}

    def check_and_add(self, nonce: str, round_id: int) -> bool:
        """
        Return True if the nonce is fresh (first use), False if already seen.
        Atomically records the nonce if fresh.
        """
        with self._lock:
            bucket = self._by_round.setdefault(round_id, set())
            if nonce in bucket:
                return False
            bucket.add(nonce)
            return True

    def evict_rounds_before(self, min_round: int) -> None:
        """Release nonce sets for rounds older than min_round."""
        with self._lock:
            stale = [r for r in self._by_round if r < min_round]
            for r in stale:
                del self._by_round[r]

    def __contains__(self, nonce: str) -> bool:
        with self._lock:
            return any(nonce in bucket for bucket in self._by_round.values())


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

class UpdateVerifier:
    """
    Coordinator-side verifier.  Stateful: holds the nonce store, the
    public-key registry, and the current round / accepted model versions.

    All checks are performed in order; the first failure short-circuits.

    Usage::

        verifier = UpdateVerifier(registry, clock_skew_seconds=30)
        verifier.set_round(current_round=1, accepted_model_versions={"sha256:abc"})
        result = verifier.verify(signed_update, expected_client_id="c0")
    """

    def __init__(
        self,
        registry: PublicKeyRegistry,
        clock_skew_seconds: float = 60.0,
    ) -> None:
        self.registry = registry
        self.clock_skew = clock_skew_seconds
        self.nonce_store = NonceStore()
        self._current_round: int = 0
        self._accepted_versions: FrozenSet[str] = frozenset()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def set_round(
        self,
        current_round: int,
        accepted_model_versions: Optional[Set[str]] = None,
    ) -> None:
        """Called by coordinator when a new round begins."""
        with self._lock:
            self.nonce_store.evict_rounds_before(current_round)
            self._current_round = current_round
            self._accepted_versions = frozenset(accepted_model_versions or set())

    # ------------------------------------------------------------------

    def verify(
        self,
        signed_update: SignedUpdate,
        expected_client_id: str,
    ) -> VerificationResult:
        """
        Run all verification checks.  Returns VerificationResult.

        Order of checks (cheapest first, cryptographic last):
          1. Nonce structure
          2. Timestamp drift
          3. Wrong client
          4. Wrong round
          5. Unknown client (no registered public key)
          6. Artifact hash (re-compute over submitted parameters)
          7. Stale model version
          8. Signature (Ed25519 verify)
          9. Nonce freshness (atomic check-and-add)
        """
        meta = signed_update.metadata
        with self._lock:
            current_round = self._current_round
            accepted_versions = self._accepted_versions

        # 1. Nonce structure: <client_id>:<round_id>:<random_hex>
        if not _nonce_well_formed(meta.nonce, meta.client_id, meta.round_id):
            return VerificationResult(
                VerificationStatus.NONCE_MALFORMED,
                f"nonce={meta.nonce!r} does not match expected pattern",
            )

        # 2. Timestamp drift
        drift = abs(int(time.time()) - meta.timestamp)
        if drift > self.clock_skew:
            return VerificationResult(
                VerificationStatus.TIMESTAMP_DRIFT,
                f"drift={drift}s > allowed={self.clock_skew}s",
            )

        # 3. Wrong client (request-level cid vs metadata cid)
        if meta.client_id != expected_client_id:
            return VerificationResult(
                VerificationStatus.WRONG_CLIENT,
                f"metadata.client_id={meta.client_id!r} != expected={expected_client_id!r}",
            )

        # 4. Wrong round
        if meta.round_id != current_round:
            return VerificationResult(
                VerificationStatus.WRONG_ROUND,
                f"metadata.round_id={meta.round_id} != current={current_round}",
            )

        # 5. Unknown client (no registered public key)
        if not self.registry.is_registered(meta.client_id):
            return VerificationResult(
                VerificationStatus.UNKNOWN_CLIENT,
                f"No public key registered for {meta.client_id!r}",
            )

        # 6. Artifact hash — recompute over submitted parameters
        expected_hash = hash_parameters(signed_update.parameters)
        if meta.artifact_hash != expected_hash:
            return VerificationResult(
                VerificationStatus.ARTIFACT_HASH_MISMATCH,
                f"metadata.artifact_hash={meta.artifact_hash!r} != computed={expected_hash!r}",
            )

        # 7. Stale model version (only enforced when versions are registered)
        if accepted_versions and meta.model_version not in accepted_versions:
            return VerificationResult(
                VerificationStatus.STALE_MODEL_VERSION,
                f"model_version={meta.model_version!r} not in accepted={accepted_versions}",
            )

        # 8. Ed25519 signature verification
        message = meta.canonical_bytes()
        if not self.registry.verify(meta.client_id, message, signed_update.signature):
            return VerificationResult(
                VerificationStatus.INVALID_SIGNATURE,
                f"Ed25519 signature invalid for client={meta.client_id!r}",
            )

        # 9. Nonce freshness (atomic — after sig is valid to avoid oracle)
        if not self.nonce_store.check_and_add(meta.nonce, meta.round_id):
            return VerificationResult(
                VerificationStatus.REUSED_NONCE,
                f"nonce={meta.nonce!r} already used in round {meta.round_id}",
            )

        return _OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nonce_well_formed(nonce: str, client_id: str, round_id: int) -> bool:
    """
    Validate nonce structure: <client_id>:<round_id>:<hex_random>

    The client_id and round_id inside the nonce must match the metadata
    fields, making cross-client nonce reuse trivially detectable.
    """
    parts = nonce.split(":")
    if len(parts) < 3:
        return False
    # client_id may itself contain colons; reconstruct by taking the last two parts
    random_part = parts[-1]
    round_part = parts[-2]
    client_part = ":".join(parts[:-2])

    if client_part != client_id:
        return False
    try:
        if int(round_part) != round_id:
            return False
    except ValueError:
        return False
    # random part should be hex and at least 8 chars
    if len(random_part) < 8:
        return False
    try:
        int(random_part, 16)
    except ValueError:
        return False
    return True
