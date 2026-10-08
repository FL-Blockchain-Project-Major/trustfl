"""
Coordinator HTTP server for distributed TrustFL.

The server implements a simple REST-like protocol over plain TCP sockets
using Python's built-in http.server — no framework dependencies.

State machine:
  WAITING      → round has not started yet (< min_clients registered)
  ROUND_ACTIVE → training in progress, clients are submitting updates
  DONE         → all rounds completed

A background monitor thread fires every 0.5 s to:
  • detect round timeouts (aggregate with whatever is available)
  • evict clients that have missed heartbeats
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from packages.crypto.trustfl_crypto.canonical import (
    canonical_artifact_bytes,
    hash_parameters,
)
from packages.crypto.trustfl_crypto.keys import PublicKeyRegistry
from packages.crypto.trustfl_crypto.signer import SignedUpdate
from packages.crypto.trustfl_crypto.verifier import UpdateVerifier

from .protocol import (
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
    SubmitUpdateRequest,
    SubmitUpdateResponse,
)

logger = logging.getLogger(__name__)

MAX_NUM_EXAMPLES = int(os.getenv("FL_MAX_NUM_EXAMPLES_PER_UPDATE", "1000000"))
MAX_CLIENT_WEIGHT_SHARE = float(os.getenv("FL_MAX_CLIENT_WEIGHT_SHARE", "0.5"))
FINALIZE_MAX_RETRIES = int(os.getenv("FL_FINALIZE_MAX_RETRIES", "5"))
FINALIZE_RETRY_BASE_SECONDS = float(os.getenv("FL_FINALIZE_RETRY_BASE_SECONDS", "1"))
INITIAL_MODEL_VERSION = "initial"
INITIAL_MODEL_VERSIONS = frozenset(
    value.strip() for value in os.getenv("FL_INITIAL_MODEL_VERSIONS", "initial,model-v1").split(",") if value.strip()
)


def _wire_message(*parts: str) -> bytes:
    """Canonical, unambiguous message format for coordinator HTTP proofs."""
    return "|".join(parts).encode("utf-8")


def _verify_public_key_signature(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """Verify an Ed25519 proof without first trusting the supplied identity."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(
            base64.b64decode(signature_b64), message
        )
        return True
    except (TypeError, ValueError):
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# FedAvg helper (inline — no external dep)
# ---------------------------------------------------------------------------

def _fedavg(
    updates: list[dict[str, Any]],
) -> list[list[float]]:
    """
    Weighted average of parameter updates.
    Each update: {"parameters": [[...], ...], "num_examples": int}
    """
    if not updates:
        raise ValueError("At least one update is required")
    reference = updates[0]["parameters"]
    if not isinstance(reference, list) or any(not isinstance(layer, list) for layer in reference):
        raise ValueError("Update parameters must be a list of layers")
    for update in updates:
        examples = update.get("num_examples")
        parameters = update.get("parameters")
        if not isinstance(examples, int) or examples <= 0:
            raise ValueError("num_examples must be a positive integer")
        if len(parameters) != len(reference):
            raise ValueError("All updates must have the same number of layers")
        for expected, layer in zip(reference, parameters, strict=True):
            if len(layer) != len(expected):
                raise ValueError("All update layers must have matching shapes")
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in layer):
                raise ValueError("Update parameters must be finite numbers")

    if not 0 < MAX_CLIENT_WEIGHT_SHARE <= 1:
        raise ValueError("FL_MAX_CLIENT_WEIGHT_SHARE must be in (0, 1]")
    claimed = [u["num_examples"] for u in updates]
    # Clip only at aggregation, after every submission is known.  This makes
    # weighting deterministic regardless of submit order and prevents a
    # self-reported count from taking more than the configured final share.
    effective = []
    for examples in claimed:
        other_total = sum(claimed) - examples
        cap = (MAX_CLIENT_WEIGHT_SHARE / (1 - MAX_CLIENT_WEIGHT_SHARE)) * other_total if MAX_CLIENT_WEIGHT_SHARE < 1 else examples
        effective.append(min(examples, max(1, int(cap))))
    total_examples = sum(effective)

    num_layers = len(updates[0]["parameters"])
    aggregated: list[list[float]] = []
    for layer_idx in range(num_layers):
        layer_len = len(updates[0]["parameters"][layer_idx])
        layer_avg = [0.0] * layer_len
        for u, examples in zip(updates, effective, strict=True):
            weight = examples / total_examples
            for i, v in enumerate(u["parameters"][layer_idx]):
                layer_avg[i] += weight * v
        aggregated.append(layer_avg)
    return aggregated


# ---------------------------------------------------------------------------
# Coordinator state (thread-safe FSM)
# ---------------------------------------------------------------------------

class CoordinatorState:
    """
    Thread-safe state container.

    Rounds are 1-indexed internally:
      current_round == 0      → WAITING (not yet started)
      0 < current_round <= N  → ROUND_ACTIVE
      current_round == N+1    → DONE
    """

    def __init__(
        self,
        min_clients: int = 2,
        num_rounds: int = 3,
        round_timeout_seconds: float = 60.0,
        heartbeat_timeout_seconds: float = 30.0,
        blockchain_client = None,
        require_signatures: bool | None = None,
        storage_client=None,
        persistence=None,
    ) -> None:
        self.min_clients = min_clients
        self.num_rounds = num_rounds
        self.round_timeout_seconds = round_timeout_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.blockchain_client = blockchain_client
        self.storage_client = storage_client
        self.persistence = persistence
        self.require_signatures = (
            require_signatures
            if require_signatures is not None
            else os.getenv("COORDINATOR_REQUIRE_SIGNATURES", "true").lower() == "true"
        )
        self.key_registry = PublicKeyRegistry()
        self.update_verifier = UpdateVerifier(self.key_registry)

        self.lock = threading.Lock()
        self.current_round: int = 0          # 0 = not started
        self.round_start_time: float | None = None
        self.global_parameters: list[list[float]] = []

        # cid → {"status": str, "last_heartbeat": float, "registered_at": float, "pubkey": str}
        self.registered_clients: dict[str, dict[str, Any]] = {}

        # cid → update dict (for the current round)
        self.pending_updates: dict[str, dict[str, Any]] = {}
        self._inflight_updates: set[str] = set()
        self._inflight_nonces: set[str] = set()
        self._inflight_registrations: set[str] = set()
        self._aggregation_in_progress = False

        # History of completed rounds
        self.round_history: list[dict[str, Any]] = []
        self._finalization_pending = False
        self._finalization_attempts = 0
        self._next_finalization_retry: float | None = None
        self._terminal_error: str | None = None
        # HTTP request nonces are independent of update nonces.  They prevent
        # replay of signed read/heartbeat requests and are bounded by expiry.
        self._request_nonces: dict[str, float] = {}

        self._done_event = threading.Event()
        if self.persistence:
            try:
                restored = self.persistence.restore_state()
                self.current_round = int(restored.get("current_round", 0))
                self.registered_clients = restored.get("registered_clients", {})
                for cid, info in self.registered_clients.items():
                    if info.get("pubkey"):
                        self.key_registry.register(cid, info["pubkey"])
                recovery = restored.get("recovery_state", {})
                if isinstance(recovery, dict):
                    self.global_parameters = recovery.get("global_parameters", [])
                    self.pending_updates = recovery.get("pending_updates", {})
                artifact = restored.get("global_artifact")
                if artifact and self.storage_client:
                    raw = self.storage_client.load_artifact(artifact["uri"], artifact["sha256_hash"])
                    restored_parameters = json.loads(raw)
                    if hash_parameters(restored_parameters) != artifact["model_version"]:
                        raise ValueError("stored global-model version does not match artifact")
                    self.global_parameters = restored_parameters
                if 0 < self.current_round <= self.num_rounds and self.require_signatures:
                    verifier_state = recovery.get("verifier", {}) if isinstance(recovery, dict) else {}
                    if verifier_state:
                        self.update_verifier.restore_state(verifier_state)
                    else:
                        self.update_verifier.set_round(self.current_round, set(INITIAL_MODEL_VERSIONS))
                if self.current_round > self.num_rounds:
                    self._done_event.set()
                logger.info("Restored coordinator state at round %d (%d clients)", self.current_round, len(self.registered_clients))
            except Exception:
                logger.exception("Coordinator state recovery failed; refusing to infer lifecycle state")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def active_clients(self) -> list[str]:
        """Clients that are ONLINE (heartbeat OK)."""
        return [
            cid
            for cid, info in self.registered_clients.items()
            if info["status"] != "OFFLINE"
        ]

    def _status_label(self) -> str:
        if self.current_round == 0:
            return "WAITING"
        if self.current_round > self.num_rounds:
            return "DONE"
        return "ROUND_ACTIVE"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_client(self, cid: str, capabilities: dict[str, Any]) -> bool:
        """Reserve a new client before chain/DB I/O, then commit atomically."""
        with self.lock:
            pubkey = capabilities.get("pubkey") or capabilities.get("public_key")
            existing = self.registered_clients.get(cid)
            if existing and existing.get("pubkey") != pubkey:
                logger.warning("Rejecting key substitution for enrolled client %s", cid)
                return False
            if cid not in self.registered_clients:
                if cid in self._inflight_registrations:
                    return False
                if self.require_signatures and not pubkey:
                    logger.warning("Rejecting client %s without a public key", cid)
                    return False
                if pubkey:
                    try:
                        self.key_registry.register(cid, pubkey)
                    except (TypeError, ValueError):
                        logger.warning("Rejecting client %s with an invalid public key", cid)
                        return False
                self._inflight_registrations.add(cid)
            else:
                # Re-registration after disconnect
                self.registered_clients[cid]["status"] = "ONLINE"
                self.registered_clients[cid]["last_heartbeat"] = time.time()
                if self.persistence:
                    self.persistence.heartbeat(cid)
                logger.info("Client re-registered: %s", cid)
                return True
        try:
            if self.blockchain_client and not self.blockchain_client.register_client(cid, pubkey):
                return False
            if self.persistence:
                self.persistence.register_client(cid, pubkey or "", capabilities)
            with self.lock:
                if cid in self.registered_clients:
                    return False
                self.registered_clients[cid] = {
                    "status": "ONLINE", "last_heartbeat": time.time(), "registered_at": time.time(),
                    "capabilities": capabilities, "pubkey": pubkey,
                }
                self._inflight_registrations.discard(cid)
                before_round = self.current_round
                self._start_next_round_if_ready_locked()
                started_round = self.current_round if before_round == 0 and self.current_round == 1 else 0
            logger.info("Client registered: %s", cid)
            if started_round:
                self._start_round_durable(started_round, INITIAL_MODEL_VERSION)
            return True
        finally:
            with self.lock:
                self._inflight_registrations.discard(cid)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self, cid: str, status: str) -> int | None:
        """Update last_heartbeat; return current_round or None if unknown."""
        with self.lock:
            if cid not in self.registered_clients:
                return None
            self.registered_clients[cid]["last_heartbeat"] = time.time()
            self.registered_clients[cid]["status"] = status if status != "OFFLINE" else "ONLINE"
            return self.current_round

    # ------------------------------------------------------------------
    # Round instructions
    # ------------------------------------------------------------------

    def get_round_instructions(self, cid: str) -> dict[str, Any]:
        with self.lock:
            if cid not in self.registered_clients:
                raise PermissionError("client is not registered")
            is_active = (
                self.current_round > 0
                and self.current_round <= self.num_rounds
                and cid not in self.pending_updates
            )
            return {
                "is_active": is_active,
                "round_id": self.current_round,
                "global_parameters": self.global_parameters,
                "config": {
                    "round": self.current_round,
                    "model_version": (
                        hash_parameters(self.global_parameters)
                        if self.global_parameters
                        else "initial"
                    ),
                    "local_epochs": 1,
                },
            }

    # ------------------------------------------------------------------
    # Update submission
    # ------------------------------------------------------------------

    def submit_update(
        self,
        cid: str,
        round_id: int,
        parameters: list[list[float]],
        num_examples: int,
        metrics: dict[str, float],
        metadata: dict[str, Any] | None = None,
        signature: str | None = None,
    ) -> bool:
        """Reserve under the lock, then perform all blocking I/O unlocked.

        A reservation prevents a duplicate client submission (or concurrent
        reuse of a nonce) from reaching storage or the chain twice.  The final
        commit checks the round again so a timeout cannot race a slow upload.
        """
        rejection: tuple[str, str, str, str] | None = None
        with self.lock:
            if cid not in self.registered_clients:
                logger.warning("Rejecting update from unknown client %s", cid)
                return False
            if round_id != self.current_round:
                logger.warning(
                    "Stale update from %s: round %d (current %d)",
                    cid, round_id, self.current_round,
                )
                return False
            if cid in self.pending_updates or cid in self._inflight_updates:
                logger.warning("Rejecting duplicate update from %s for round %d", cid, round_id)
                return False
            if not self._valid_update_parameters(parameters, num_examples, metrics):
                logger.warning("Rejecting malformed update from %s", cid)
                return False

            update_id = f"update_{cid}_{round_id}"
            nonce = metadata.get("nonce") if metadata else f"nonce_{update_id}"
            verified = False
            signed_update = None
            if self.require_signatures:
                if not metadata or not signature:
                    logger.warning("Rejecting unsigned update from %s", cid)
                    return False
                try:
                    signed_update = SignedUpdate.from_dict({
                        "metadata": metadata, "signature": signature,
                        "parameters": parameters, "num_examples": num_examples, "metrics": metrics,
                    })
                except (KeyError, TypeError, ValueError):
                    logger.warning("Rejecting malformed signed update from %s", cid)
                    return False
                # Do not consume the nonce until all later durable operations succeed.
                verification = self.update_verifier.verify(signed_update, cid, consume_nonce=False)
                if not verification.ok:
                    logger.warning("Rejected update from %s: %s", cid, verification.status.value)
                    rejection = (update_id, nonce, metadata.get("artifact_hash", "sha256:rejected"), verification.status.value)
                else:
                    verified = True
            if rejection:
                pass
            elif nonce in self._inflight_nonces:
                rejection = (update_id, nonce, metadata.get("artifact_hash", "sha256:rejected") if metadata else "sha256:rejected", "REUSED_NONCE")
            else:
                self._inflight_updates.add(cid)
                self._inflight_nonces.add(nonce)
        if rejection:
            self._audit_rejection(update_id, cid, round_id, *rejection[1:])
            return False
        try:
            artifact_data = canonical_artifact_bytes(parameters, num_examples, metrics)
            stored_artifact = (
                self.storage_client.save_artifact(artifact_data, str(round_id), round_id, cid, update_id)
                if self.storage_client else None
            )
            artifact_hash = stored_artifact.sha256_hash if stored_artifact else (
                metadata["artifact_hash"] if metadata else "0x_dummy_hash"
            )
            if metadata and metadata.get("artifact_hash") and stored_artifact and metadata["artifact_hash"] != artifact_hash:
                raise ValueError("ARTIFACT_HASH_MISMATCH")
            if self.blockchain_client:
                if not self.blockchain_client.submit_update(update_id, round_id, cid, artifact_hash, nonce):
                    raise OSError("BLOCKCHAIN_SUBMIT_FAILED")
                if verified and not self.blockchain_client.mark_verification_state(update_id, True):
                    raise OSError("BLOCKCHAIN_VERIFICATION_FAILED")
            if self.persistence:
                self.persistence.record_update(
                    update_id, cid, round_id, stored_artifact.uri if stored_artifact else None,
                    artifact_hash, num_examples, metrics, nonce, verified,
                )
        except (TypeError, ValueError, OSError) as exc:
            reason = str(exc) if str(exc).isupper() else "DURABLE_WRITE_FAILED"
            self._audit_rejection(update_id, cid, round_id, nonce, "sha256:rejected", reason)
            with self.lock:
                self._inflight_updates.discard(cid)
                self._inflight_nonces.discard(nonce)
            return False
        with self.lock:
            if self.current_round != round_id or cid in self.pending_updates:
                self._inflight_updates.discard(cid)
                self._inflight_nonces.discard(nonce)
                return False
            if signed_update and not self.update_verifier.consume_nonce(signed_update):
                self._inflight_updates.discard(cid)
                self._inflight_nonces.discard(nonce)
                return False
            self.pending_updates[cid] = {
                "parameters": parameters, "num_examples": num_examples, "metrics": metrics,
                "update_id": update_id, "artifact_uri": stored_artifact.uri if stored_artifact else None,
                "artifact_hash": artifact_hash,
            }
            self._inflight_updates.discard(cid)
            self._inflight_nonces.discard(nonce)
            self._save_recovery_locked()
            should_aggregate = set(self.pending_updates.keys()) >= set(self.active_clients)
        if should_aggregate:
            self._aggregate_round(timed_out=False)
        return True

    def _valid_update_parameters(
        self, parameters: Any, num_examples: Any, metrics: Any
    ) -> bool:
        """Validate untrusted numerical data before storage, chain, or aggregation I/O."""
        if not isinstance(num_examples, int) or isinstance(num_examples, bool) or not 0 < num_examples <= MAX_NUM_EXAMPLES:
            return False
        if not isinstance(parameters, list) or not parameters or any(not isinstance(layer, list) for layer in parameters):
            return False
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
               for layer in parameters for value in layer):
            return False
        if not isinstance(metrics, dict) or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in metrics.values()):
            return False
        # Once a global model exists every submitted layer must match it exactly.
        if self.global_parameters and (
            len(parameters) != len(self.global_parameters)
            or any(len(layer) != len(expected) for layer, expected in zip(parameters, self.global_parameters, strict=True))
        ):
            return False
        return True

    def _audit_rejection(
        self, update_id: str, cid: str, round_id: int, nonce: str, artifact_hash: str, reason: str
    ) -> None:
        """Record a verified rejection without retaining model payloads.

        The registry requires Submitted -> Rejected, so submission precedes
        the state transition and both client methods are idempotent.
        """
        if self.blockchain_client:
            if self.blockchain_client.submit_update(update_id, round_id, cid, artifact_hash, nonce):
                self.blockchain_client.mark_verification_state(update_id, False, reason)
        if self.persistence:
            self.persistence.record_rejection(update_id, cid, round_id, nonce, artifact_hash, reason)

    def _save_recovery_locked(self) -> None:
        if self.persistence and self.current_round > 0:
            self.persistence.save_recovery_state(
                self.current_round,
                {
                    "global_parameters": self.global_parameters,
                    "pending_updates": self.pending_updates,
                    "verifier": self.update_verifier.snapshot_state(),
                    "finalization": {
                        "pending": self._finalization_pending,
                        "attempts": self._finalization_attempts,
                        "next_retry_at": self._next_finalization_retry,
                        "terminal_error": self._terminal_error,
                    },
                },
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self, detailed: bool = True) -> dict[str, Any]:
        with self.lock:
            if not detailed:
                return {"status": self._status_label()}
            return {
                "status": self._status_label(),
                "current_round": self.current_round,
                "num_rounds": self.num_rounds,
                "active_clients": list(self.active_clients),
                "round_history": list(self.round_history),
                "finalization": {
                    "pending": self._finalization_pending,
                    "attempts": self._finalization_attempts,
                    "next_retry_at": self._next_finalization_retry,
                    "terminal_error": self._terminal_error,
                },
            }

    def verify_request_proof(
        self, cid: str, method: str, path: str, timestamp: str, nonce: str, signature: str
    ) -> bool:
        """Authenticate a request as a registered client, including replay protection."""
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False
        now = time.time()
        if not cid or not nonce or abs(now - ts) > 60:
            return False
        with self.lock:
            expiry = self._request_nonces.get(nonce)
            if expiry and expiry > now:
                return False
            info = self.registered_clients.get(cid)
            if not info or not info.get("pubkey"):
                return False
            valid = _verify_public_key_signature(
                info["pubkey"], _wire_message("trustfl-request-v1", cid, method, path, timestamp, nonce), signature
            )
            if valid:
                self._request_nonces[nonce] = now + 120
                stale = [value for value, until in self._request_nonces.items() if until <= now]
                for value in stale:
                    del self._request_nonces[value]
            return valid

    # ------------------------------------------------------------------
    # Monitor (called by background thread — acquires lock internally)
    # ------------------------------------------------------------------

    def monitor_tick(self) -> None:
        """Called periodically. Evicts dead clients; triggers timeout aggregation."""
        aggregate_timeout = False
        retry_finalize = False
        with self.lock:
            now = time.time()
            # Evict clients that have missed heartbeats
            for cid, info in self.registered_clients.items():
                if (
                    info["status"] != "OFFLINE"
                    and now - info["last_heartbeat"] > self.heartbeat_timeout_seconds
                ):
                    info["status"] = "OFFLINE"
                    logger.warning("Client %s marked OFFLINE (heartbeat timeout)", cid)

            # Check round timeout
            if (
                self.current_round > 0
                and self.current_round <= self.num_rounds
                and self.round_start_time is not None
                and now - self.round_start_time > self.round_timeout_seconds
            ):
                logger.warning(
                    "Round %d timed out after %.1f s",
                    self.current_round, now - self.round_start_time,
                )
                aggregate_timeout = True
            elif self._finalization_pending and (
                self._next_finalization_retry is None or now >= self._next_finalization_retry
            ):
                # Aggregation already succeeded; only reconcile its durable
                # finalization.  Do not create a second history record.
                retry_finalize = True
        if aggregate_timeout:
            self._aggregate_round(timed_out=True)
        elif retry_finalize:
            self._retry_finalization()

    # ------------------------------------------------------------------
    # Internal (must be called while holding self.lock)
    # ------------------------------------------------------------------

    def _aggregate_round(self, timed_out: bool = False) -> None:
        """Snapshot under lock, aggregate/chain-finalize unlocked, then commit."""
        with self.lock:
            if self._aggregation_in_progress or not (0 < self.current_round <= self.num_rounds):
                return
            self._aggregation_in_progress = True
            round_id = self.current_round
            updates = list(self.pending_updates.values())
        try:
            if len(updates) < self.min_clients:
                if self.persistence:
                    self.persistence.fail_round(round_id)
                with self.lock:
                    if self.current_round == round_id:
                        self.round_history.append({"round": round_id, "num_successful_clients": len(updates), "timed_out": timed_out, "status": "FAILED", "metrics": _avg_metrics([u["metrics"] for u in updates])})
                        self.pending_updates.clear()
                        self.current_round += 1
                return
            parameters = _fedavg(updates)
            global_artifact = None
            if self.storage_client:
                global_artifact = self.storage_client.save_artifact(
                    json.dumps(parameters, separators=(",", ":")).encode(),
                    hash_parameters(parameters), round_id, None, None,
                )
                if self.persistence:
                    self.persistence.record_global_model(
                        round_id, global_artifact.uri, global_artifact.sha256_hash, hash_parameters(parameters)
                    )
            for update in updates:
                if self.blockchain_client and update.get("update_id"):
                    self.blockchain_client.record_aggregation(update["update_id"])
            finalized = not self.blockchain_client or self.blockchain_client.finalize_round(round_id, hash_parameters(parameters))
            if finalized and self.persistence:
                self.persistence.finalize_round(round_id)
            with self.lock:
                if self.current_round != round_id:
                    return
                self.global_parameters = parameters
                self.round_history.append({"round": round_id, "num_successful_clients": len(updates), "timed_out": timed_out, "metrics": _avg_metrics([u["metrics"] for u in updates])})
                if not finalized:
                    self.round_start_time = None
                    self._finalization_attempts += 1
                    self._finalization_pending = self._finalization_attempts < FINALIZE_MAX_RETRIES
                    self._next_finalization_retry = time.time() + FINALIZE_RETRY_BASE_SECONDS * (2 ** (self._finalization_attempts - 1))
                    self._terminal_error = None if self._finalization_pending else "blockchain finalization retry budget exhausted"
                    self._save_recovery_locked()
                    return
                self.pending_updates.clear()
                self.current_round += 1
                if self.current_round > self.num_rounds:
                    self._done_event.set()
                    return
                self.round_start_time = time.time()
                if self.require_signatures:
                    self.update_verifier.set_round(self.current_round, {hash_parameters(self.global_parameters)})
                next_round = self.current_round
                model_version = hash_parameters(self.global_parameters)
            self._start_round_durable(next_round, model_version)
        finally:
            with self.lock:
                self._aggregation_in_progress = False

    def _retry_finalization(self) -> None:
        """Retry a previously aggregated finalization without holding state lock."""
        with self.lock:
            if not self._finalization_pending:
                return
            round_id, model_version = self.current_round, hash_parameters(self.global_parameters)
        succeeded = not self.blockchain_client or self.blockchain_client.finalize_round(round_id, model_version)
        if succeeded and self.persistence:
            self.persistence.finalize_round(round_id)
        with self.lock:
            if succeeded:
                self._finalization_pending = False
                self._finalization_attempts = 0
                self._next_finalization_retry = None
                self.pending_updates.clear()
                self.current_round += 1
                if self.current_round <= self.num_rounds:
                    self.round_start_time = time.time()
                    if self.require_signatures:
                        self.update_verifier.set_round(self.current_round, {model_version})
                    next_round = self.current_round
                else:
                    self._done_event.set()
                    next_round = 0
            else:
                self._finalization_attempts += 1
                self._finalization_pending = self._finalization_attempts < FINALIZE_MAX_RETRIES
                self._next_finalization_retry = time.time() + FINALIZE_RETRY_BASE_SECONDS * (2 ** (self._finalization_attempts - 1))
                if not self._finalization_pending:
                    self._terminal_error = "blockchain finalization retry budget exhausted"
            self._save_recovery_locked()
        if succeeded and next_round:
            self._start_round_durable(next_round, model_version)

    def _start_next_round_if_ready_locked(self) -> None:
        """Start round 1 when enough clients have registered."""
        if (
            self.current_round == 0
            and len(self.active_clients) >= self.min_clients
        ):
            self.current_round = 1
            self.round_start_time = time.time()
            if self.require_signatures:
                self.update_verifier.set_round(self.current_round, set(INITIAL_MODEL_VERSIONS))

            logger.info(
                "Round 1 started with %d clients", len(self.active_clients)
            )

    def _start_round_durable(self, round_id: int, model_version: str) -> None:
        """Chain and DB transition performed after the in-memory start commit."""
        if self.blockchain_client:
            if not self.blockchain_client.create_round(round_id, model_version):
                logger.error("Blockchain round %d creation failed", round_id)
                return
            if not self.blockchain_client.activate_round(round_id):
                logger.error("Blockchain round %d activation failed", round_id)
                return
        if self.persistence:
            self.persistence.start_round(round_id, model_version)

    def _aggregate_round_locked(self, timed_out: bool = False) -> None:
        """Run FedAvg over pending_updates and advance the round counter."""
        updates = list(self.pending_updates.values())
        quorum_met = len(updates) >= self.min_clients
        if not quorum_met:
            logger.error("Round %d failed quorum: %d < %d", self.current_round, len(updates), self.min_clients)
            self.round_history.append({"round": self.current_round, "num_successful_clients": len(updates), "timed_out": timed_out, "status": "FAILED", "metrics": _avg_metrics([u["metrics"] for u in updates])})
            if self.persistence:
                self.persistence.fail_round(self.current_round)
            self._advance_round_locked(finalize=False)
            return
        try:
            self.global_parameters = _fedavg(updates)
        except (TypeError, ValueError, OverflowError) as exc:
            # Defense in depth: malformed in-memory data can never wedge monitor_tick.
            logger.exception("Round %d aggregation rejected: %s", self.current_round, exc)
            self.round_history.append({"round": self.current_round, "num_successful_clients": 0, "timed_out": timed_out, "status": "FAILED", "metrics": {}})
            if self.persistence:
                self.persistence.fail_round(self.current_round)
            self._advance_round_locked(finalize=False)
            return
        if updates:

            if self.blockchain_client:
                for u in updates:
                    update_id = u.get("update_id")
                    if update_id:
                        self.blockchain_client.record_aggregation(update_id)
        else:
            logger.warning("No updates to aggregate for round %d", self.current_round)

        record = {
            "round": self.current_round,
            "num_successful_clients": len(updates),
            "timed_out": timed_out,
            "metrics": _avg_metrics([u["metrics"] for u in updates]),
        }
        self.round_history.append(record)
        logger.info(
            "Round %d aggregated: %d clients, timed_out=%s",
            self.current_round, len(updates), timed_out,
        )

        self._advance_round_locked()

    def _advance_round_locked(self, finalize: bool = True) -> None:
        # Finalize the current round
        chain_finalized = True
        if finalize and self.blockchain_client:
            chain_finalized = self.blockchain_client.finalize_round(self.current_round, hash_parameters(self.global_parameters))
        if finalize and chain_finalized and self.persistence:
            self.persistence.finalize_round(self.current_round)
        elif finalize and not chain_finalized:
            # Keep the already aggregated update set and freeze the timer.  A
            # later monitor tick retries finalization; it never aggregates it again.
            self.round_start_time = None
            self._finalization_attempts += 1
            if self._finalization_attempts >= FINALIZE_MAX_RETRIES:
                self._finalization_pending = False
                self._terminal_error = "blockchain finalization retry budget exhausted"
                logger.critical("Round %d finalization is terminally blocked after %d attempts; operator recovery required", self.current_round, self._finalization_attempts)
                self._save_recovery_locked()
                return
            delay = FINALIZE_RETRY_BASE_SECONDS * (2 ** (self._finalization_attempts - 1))
            self._next_finalization_retry = time.time() + delay
            self._finalization_pending = True
            logger.error("Round %d remains unfinalized; retry %d/%d in %.1fs", self.current_round, self._finalization_attempts, FINALIZE_MAX_RETRIES, delay)
            self._save_recovery_locked()
            return

        self._finalization_pending = False
        self._finalization_attempts = 0
        self._next_finalization_retry = None
        self._terminal_error = None
        self.pending_updates.clear()

        self.current_round += 1
        if self.current_round > self.num_rounds:
            logger.info("All %d rounds completed.", self.num_rounds)
            self._done_event.set()
        else:
            self.round_start_time = time.time()
            if self.require_signatures:
                self.update_verifier.set_round(
                    self.current_round,
                    accepted_model_versions={hash_parameters(self.global_parameters)}
                    if self.global_parameters
                    else {INITIAL_MODEL_VERSION},
                )
            if self.blockchain_client:
                bc_ok = self.blockchain_client.create_round(self.current_round, hash_parameters(self.global_parameters) if self.global_parameters else INITIAL_MODEL_VERSION)
                if not bc_ok:
                    logger.error("Blockchain round %d creation failed", self.current_round)
                else:
                    if not self.blockchain_client.activate_round(self.current_round):
                        logger.error("Blockchain round %d activation failed", self.current_round)
            if self.persistence:
                self.persistence.start_round(
                    self.current_round,
                    hash_parameters(self.global_parameters) if self.global_parameters else INITIAL_MODEL_VERSION,
                )
            logger.info("Round %d started.", self.current_round)

    # ------------------------------------------------------------------
    # Blocking wait
    # ------------------------------------------------------------------

    def wait_until_done(self, timeout: float | None = None) -> bool:
        return self._done_event.wait(timeout=timeout)


def _avg_metrics(metrics_list: list[dict[str, float]]) -> dict[str, float]:
    if not metrics_list:
        return {}
    keys = metrics_list[0].keys()
    return {
        k: sum(m.get(k, 0.0) for m in metrics_list) / len(metrics_list)
        for k in keys
    }


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    MAX_BODY_BYTES = 1_048_576
    """Minimal HTTP handler wired to CoordinatorState."""

    state: CoordinatorState  # injected by server factory

    def log_message(self, fmt: str, *args: Any) -> None:  # suppress access log
        pass

    # ---- routing ----------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond_json(200, {"status": "ok"})
            return
        cid = self.headers.get("X-TrustFL-Client-ID", "")
        if not self._request_authorized(cid):
            self._respond_json(401, {"error": "authentication required"})
        elif self.path == "/status":
            self._respond_json(200, self.state.get_status())
        elif self.path.startswith("/round/instructions/"):
            requested_cid = self.path.split("/")[-1]
            if requested_cid != cid:
                self._respond_json(403, {"error": "client identity mismatch"})
            else:
                self._respond_json(200, self.state.get_round_instructions(cid))
        else:
            self._respond_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            data = self._read_body()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if self.path == "/register":
            if not self._registration_authorized(data):
                self._respond_json(401, {"error": "invalid enrollment proof or credential"})
                return
        elif not self._request_authorized(str(data.get("client_id", ""))):
            self._respond_json(401, {"error": "client authentication required"})
            return
        try:
            self._do_post(data)
        except (KeyError, TypeError, ValueError) as exc:
            self._respond_json(400, {"error": f"invalid request: {exc}"})

    def _do_post(self, data: dict[str, Any]) -> None:
        if self.path == "/register":
            req = RegisterRequest.from_dict(data)
            ok = self.state.register_client(req.client_id, req.capabilities)
            resp = RegisterResponse(accepted=ok)
            self._respond_json(200, resp.__dict__)

        elif self.path == "/heartbeat":
            req = HeartbeatRequest.from_dict(data)
            rnd = self.state.heartbeat(req.client_id, req.status)
            if rnd is None:
                self._respond_json(404, {"error": "unknown client"})
            else:
                resp = HeartbeatResponse(ok=True, server_round=rnd)
                self._respond_json(200, resp.__dict__)

        elif self.path == "/submit":
            req = SubmitUpdateRequest.from_dict(data)
            ok = self.state.submit_update(
                req.client_id,
                req.round_id,
                req.parameters,
                req.num_examples,
                req.metrics,
                req.metadata,
                req.signature,
            )
            resp = SubmitUpdateResponse(accepted=ok)
            self._respond_json(200, resp.__dict__)

        else:
            self._respond_json(404, {"error": "not found"})

    # ---- helpers ----------------------------------------------------------

    def _read_body(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            self._respond_json(413, {"error": "chunked request bodies are not supported"})
            raise ValueError("chunked request body rejected")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            self._respond_json(400, {"error": "valid Content-Length is required"})
            raise ValueError("invalid Content-Length")
        length = int(raw_length)
        if length > self.MAX_BODY_BYTES:
            self._respond_json(413, {"error": "request body too large"})
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            self._respond_json(400, {"error": "JSON body must be an object"})
            raise ValueError("JSON body must be an object")
        return data

    def _insecure_dev_enabled(self) -> bool:
        return os.getenv("COORDINATOR_INSECURE_DEV_AUTH", "false").lower() == "true"

    def _registration_authorized(self, data: dict[str, Any]) -> bool:
        """Require a proof of possession and an operator-provisioned identity binding."""
        # Disposable integration/development environments can opt in to the
        # legacy shared-token enrollment flow.  This branch is intentionally
        # before proof validation because old clients do not carry a proof.
        if self._insecure_dev_enabled():
            return self._legacy_token_authorized(data)
        cid = str(data.get("client_id", ""))
        capabilities = data.get("capabilities") or {}
        pubkey = capabilities.get("pubkey") or capabilities.get("public_key")
        nonce = str(capabilities.get("registration_nonce", ""))
        signature = str(capabilities.get("registration_signature", ""))
        if not cid or not pubkey or not nonce or not signature:
            return False
        if not _verify_public_key_signature(pubkey, _wire_message("trustfl-registration-v1", cid, pubkey, nonce), signature):
            return False
        try:
            allowlist = json.loads(os.getenv("COORDINATOR_ENROLLMENT_ALLOWLIST", "{}"))
        except json.JSONDecodeError:
            logger.error("COORDINATOR_ENROLLMENT_ALLOWLIST is not valid JSON")
            return False
        expected_key = allowlist.get(cid)
        # An explicit per-client allow-list is mandatory outside explicitly
        # insecure development.  A shared token is only a second dev factor.
        if expected_key:
            return hmac.compare_digest(str(expected_key), str(pubkey))
        return False

    def _request_authorized(self, cid: str) -> bool:
        if self._insecure_dev_enabled():
            return self._legacy_token_authorized({})
        return self.state.verify_request_proof(
            cid,
            self.command,
            self.path,
            self.headers.get("X-TrustFL-Timestamp", ""),
            self.headers.get("X-TrustFL-Nonce", ""),
            self.headers.get("X-TrustFL-Signature", ""),
        )

    def _legacy_token_authorized(self, data: dict[str, Any]) -> bool:
        expected = os.getenv("COORDINATOR_ENROLLMENT_TOKEN", "")
        if not expected:
            return True
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or str(data.get("credential", ""))
        return hmac.compare_digest(supplied, expected)

    def _respond_json(self, code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class CoordinatorServer:
    """
    Wraps CoordinatorState + HTTPServer in one convenient object.

    Usage::

        server = CoordinatorServer(host="0.0.0.0", port=8100, min_clients=2)
        server.start()           # non-blocking, returns immediately
        server.state.wait_until_done(timeout=120)
        server.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8100,
        min_clients: int = 2,
        num_rounds: int = 3,
        round_timeout_seconds: float = 60.0,
        heartbeat_timeout_seconds: float = 30.0,
        monitor_interval_seconds: float = 0.5,
        blockchain_client = None,
        require_signatures: bool | None = None,
        storage_client = None,
        persistence=None,
    ) -> None:
        self.host = host
        self.port = port
        self.monitor_interval = monitor_interval_seconds
        self.blockchain_client = blockchain_client

        self.state = CoordinatorState(
            min_clients=min_clients,
            num_rounds=num_rounds,
            round_timeout_seconds=round_timeout_seconds,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            blockchain_client=self.blockchain_client,
            require_signatures=require_signatures,
            storage_client=storage_client,
            persistence=persistence,
        )

        # Build the HTTP server with the state injected via closure
        state = self.state

        class BoundHandler(_Handler):
            pass

        BoundHandler.state = state
        class TimeoutThreadingHTTPServer(ThreadingHTTPServer):
            daemon_threads = True
            def get_request(self):  # type: ignore[no-untyped-def]
                sock, address = super().get_request()
                sock.settimeout(float(os.getenv("COORDINATOR_CONNECTION_TIMEOUT_SECONDS", "10")))
                return sock, address

        self._httpd = TimeoutThreadingHTTPServer((host, port), BoundHandler)
        self._httpd.timeout = 0.5   # so serve_forever can be interrupted quickly

        self._http_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start HTTP + monitor threads (non-blocking)."""
        self._http_thread = threading.Thread(
            target=self._serve_http, daemon=True, name="coord-http"
        )
        self._http_thread.start()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="coord-monitor"
        )
        self._monitor_thread.start()
        logger.info("CoordinatorServer started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._stop_event.set()
        self._httpd.shutdown()
        if self._http_thread:
            self._http_thread.join(timeout=3)
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        logger.info("CoordinatorServer stopped.")

    # ------------------------------------------------------------------

    def _serve_http(self) -> None:
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            pass

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.state.monitor_tick()
            except Exception as exc:
                logger.error("Monitor error: %s", exc)
            time.sleep(self.monitor_interval)
