"""Coordinator persistence adapter for the API control-plane database."""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class CoordinatorPersistence:
    """Write coordinator lifecycle events to the API's SQLAlchemy models.

    The coordinator remains usable in unit tests without this adapter. In a
    deployed stack the adapter is created by the coordinator process and uses
    the same DATABASE_URL as the API.
    """

    def __init__(self) -> None:
        from apps.api.api.db.models import (
            BlockchainOutbox,
            Client,
            ClientLifecycleStatus,
            CoordinatorLease,
            Federation,
            FederationStatus,
            ModelArtifact,
            Round,
            RoundStatus,
            Update,
            UpdateStatus,
        )
        from apps.api.api.db.session import SessionLocal

        self.SessionLocal = SessionLocal
        self.Client = Client
        self.Federation = Federation
        self.ModelArtifact = ModelArtifact
        self.Round = Round
        self.Update = Update
        self.FederationStatus = FederationStatus
        self.RoundStatus = RoundStatus
        self.UpdateStatus = UpdateStatus
        self.BlockchainOutbox = BlockchainOutbox
        self.ClientLifecycleStatus = ClientLifecycleStatus
        self.CoordinatorLease = CoordinatorLease
        self.federation_id = os.getenv("FL_FEDERATION_ID", "fed-default")
        self.holder_id = os.getenv(
            "COORDINATOR_INSTANCE_ID", f"{socket.gethostname()}-{uuid.uuid4().hex}"
        )

    def _session(self):
        return self.SessionLocal()

    def acquire_lease(self, ttl_seconds: int = 30) -> bool:
        """Acquire or renew the federation lease; increment fencing on takeover."""
        now = datetime.now(UTC)
        try:
            with self._session() as db:
                row = (
                    db.query(self.CoordinatorLease)
                    .filter(self.CoordinatorLease.federation_id == self.federation_id)
                    .with_for_update()
                    .one_or_none()
                )
                if row is None:
                    row = self.CoordinatorLease(
                        federation_id=self.federation_id,
                        holder_id=self.holder_id,
                        fencing_token=1,
                        expires_at=now + timedelta(seconds=ttl_seconds),
                    )
                    db.add(row)
                else:
                    expires_at = row.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if row.holder_id != self.holder_id and expires_at > now:
                        return False
                    if row.holder_id != self.holder_id:
                        row.fencing_token += 1
                    row.holder_id = self.holder_id
                    row.expires_at = now + timedelta(seconds=ttl_seconds)
                db.commit()
                return True
        except IntegrityError:
            return False

    def release_lease(self) -> None:
        with self._session() as db:
            row = db.get(self.CoordinatorLease, self.federation_id)
            if row is not None and row.holder_id == self.holder_id:
                row.expires_at = datetime.now(UTC)
                db.commit()

    def ensure_federation(self, min_clients: int, max_rounds: int) -> None:
        with self._session() as db:
            federation = db.get(self.Federation, self.federation_id)
            if federation is None:
                federation = self.Federation(
                    id=self.federation_id,
                    name=os.getenv("FL_FEDERATION_NAME", "TrustFL Federation"),
                    status=self.FederationStatus.ACTIVE,
                    min_clients=min_clients,
                    max_rounds=max_rounds,
                )
                db.add(federation)
            db.commit()

    def register_client(self, client_id: str, public_key: str, capabilities: dict) -> None:
        with self._session() as db:
            row = db.get(self.Client, client_id)
            if row is None:
                if os.getenv("ENVIRONMENT", "development").lower() == "production":
                    raise PermissionError(
                        f"client {client_id} must be enrolled before coordinator registration"
                    )
                row = self.Client(
                    id=client_id,
                    federation_id=self.federation_id,
                    public_key_b64=public_key,
                )
                db.add(row)
            elif row.public_key_b64 and row.public_key_b64 != public_key:
                raise ValueError(f"public key substitution rejected for client {client_id}")
            elif row.lifecycle_status != self.ClientLifecycleStatus.ACTIVE:
                raise PermissionError(f"client {client_id} is not actively enrolled")
            row.is_active = True
            row.last_seen_at = datetime.now(UTC)
            row.capabilities = json.dumps(capabilities, sort_keys=True)
            db.commit()

    def heartbeat(self, client_id: str) -> None:
        with self._session() as db:
            row = db.get(self.Client, client_id)
            if row is not None:
                row.last_seen_at = datetime.now(UTC)
                row.is_active = True
                db.commit()

    def start_round(self, round_number: int, model_version: str) -> None:
        with self._session() as db:
            round_id = f"{self.federation_id}_round{round_number}"
            row = db.get(self.Round, round_id)
            if row is None:
                row = self.Round(
                    id=round_id,
                    federation_id=self.federation_id,
                    round_number=round_number,
                )
                db.add(row)
            elif row.status.value in {"COMPLETED", "FINALIZED"}:
                return
            elif row.status.value not in {"CREATED", "RECOVERY_REQUIRED", "COLLECTING"}:
                raise ValueError(f"invalid round start from {row.status.value}")
            row.status = self.RoundStatus.COLLECTING
            row.model_version = model_version
            row.started_at = datetime.now(UTC)
            db.commit()

    def transition_round(
        self,
        round_number: int,
        expected: set[str],
        target: str,
        recovery_state: dict | None = None,
    ) -> bool:
        """Atomically transition a round, rejecting stale coordinator writers."""
        allowed = {
            "CREATED": {"COLLECTING", "FAILED", "RECOVERY_REQUIRED"},
            "COLLECTING": {"VALIDATING", "FAILED", "RECOVERY_REQUIRED"},
            "VALIDATING": {"AGGREGATING", "FAILED", "RECOVERY_REQUIRED"},
            "AGGREGATING": {"COMMITTING", "FAILED", "RECOVERY_REQUIRED"},
            "COMMITTING": {"COMPLETED", "FAILED", "RECOVERY_REQUIRED"},
            "ACTIVE": {"AGGREGATING", "FAILED", "RECOVERY_REQUIRED"},
            "FINALIZED": set(),
            "COMPLETED": set(),
            "FAILED": {"RECOVERY_REQUIRED"},
            "RECOVERY_REQUIRED": {"COLLECTING", "VALIDATING", "FAILED"},
        }
        with self._session() as db:
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is None or row.status.value not in expected:
                return False
            if target not in allowed.get(row.status.value, set()):
                return False
            row.status = target
            if recovery_state is not None:
                row.recovery_state = json.dumps(recovery_state, sort_keys=True)
            db.commit()
            return True

    def record_update(
        self,
        update_id: str,
        client_id: str,
        round_number: int,
        artifact_uri: str | None,
        artifact_hash: str,
        num_examples: int,
        metrics: dict[str, float],
        nonce: str,
        verified: bool = False,
        blockchain_events: list[dict] | None = None,
    ) -> None:
        with self._session() as db:
            round_id = f"{self.federation_id}_round{round_number}"
            row = db.get(self.Update, update_id)
            if row is not None:
                if (
                    row.round_id != round_id
                    or row.client_id != client_id
                    or row.artifact_hash not in (None, artifact_hash)
                    or row.nonce not in (None, nonce)
                ):
                    raise ValueError("CONFLICTING_DUPLICATE_UPDATE")
                if row.status in (self.UpdateStatus.VERIFIED, self.UpdateStatus.AGGREGATED):
                    return
            else:
                row = self.Update(
                    id=update_id,
                    round_id=round_id,
                    client_id=client_id,
                )
                db.add(row)
            row.status = self.UpdateStatus.VERIFIED if verified else self.UpdateStatus.SUBMITTED
            row.artifact_hash = artifact_hash
            row.artifact_id = update_id
            row.num_examples = num_examples
            row.loss = metrics.get("loss")
            row.nonce = nonce
            row.verified_at = datetime.now(UTC) if verified else None
            if artifact_uri:
                artifact = db.get(self.ModelArtifact, update_id)
                if artifact is None:
                    db.add(
                        self.ModelArtifact(
                            id=update_id,
                            federation_id=self.federation_id,
                            round_number=round_number,
                            client_id=client_id,
                            uri=artifact_uri,
                            sha256_hash=artifact_hash,
                            model_version=str(round_number),
                        )
                    )
            for event in blockchain_events or []:
                self._enqueue_in_session(db, event)
            db.commit()

    def _enqueue_in_session(self, db, event: dict) -> None:
        key = str(event["idempotency_key"])
        existing = (
            db.query(self.BlockchainOutbox)
            .filter(self.BlockchainOutbox.idempotency_key == key)
            .one_or_none()
        )
        if existing is None:
            now = datetime.now(UTC)
            db.add(
                self.BlockchainOutbox(
                    id=str(event.get("id", key)),
                    idempotency_key=key,
                    event_type=str(event["event_type"]),
                    payload=json.dumps(event.get("payload", {}), sort_keys=True),
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )

    def enqueue_blockchain_event(
        self, event_type: str, idempotency_key: str, payload: dict
    ) -> None:
        with self._session() as db:
            self._enqueue_in_session(
                db,
                {
                    "id": idempotency_key,
                    "event_type": event_type,
                    "idempotency_key": idempotency_key,
                    "payload": payload,
                },
            )
            db.commit()

    def pending_blockchain_events(self, limit: int = 50) -> list[dict]:
        with self._session() as db:
            now = datetime.now(UTC)
            rows = (
                db.query(self.BlockchainOutbox)
                .filter(
                    self.BlockchainOutbox.status.in_(("PENDING", "RETRY")),
                    self.BlockchainOutbox.next_attempt_at <= now,
                )
                .order_by(self.BlockchainOutbox.created_at)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "idempotency_key": row.idempotency_key,
                    "event_type": row.event_type,
                    "payload": json.loads(row.payload),
                    "attempts": row.attempts,
                }
                for row in rows
            ]

    def claim_blockchain_events(self, limit: int = 10) -> list[dict]:
        """Claim due work so multiple coordinators do not process it concurrently."""
        with self._session() as db:
            now = datetime.now(UTC)
            rows = (
                db.query(self.BlockchainOutbox)
                .filter(
                    self.BlockchainOutbox.status.in_(("PENDING", "RETRY")),
                    self.BlockchainOutbox.next_attempt_at <= now,
                )
                .order_by(self.BlockchainOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
                .all()
            )
            result = []
            for row in rows:
                row.status = "PROCESSING"
                result.append(
                    {
                        "id": row.id,
                        "event_type": row.event_type,
                        "payload": json.loads(row.payload),
                    }
                )
            db.commit()
            return result

    def mark_blockchain_retry(
        self, event_id: str, error: str, max_attempts: int | None = None
    ) -> None:
        max_attempts = max_attempts or int(os.getenv("BLOCKCHAIN_OUTBOX_MAX_ATTEMPTS", "8"))
        with self._session() as db:
            row = db.get(self.BlockchainOutbox, event_id)
            if row is None:
                return
            row.attempts += 1
            row.last_error = error[:512]
            row.status = "FAILED" if row.attempts >= max_attempts else "RETRY"
            row.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2 ** min(row.attempts, 8))
            )
            db.commit()

    def mark_blockchain_submitted(self, event_id: str, tx_hash: str) -> None:
        with self._session() as db:
            row = db.get(self.BlockchainOutbox, event_id)
            if row is None:
                return
            row.status = "SUBMITTED"
            row.tx_hash = tx_hash
            row.updated_at = datetime.now(UTC)
            db.commit()

    def mark_blockchain_processed(self, event_id: str, tx_hash: str | None = None) -> None:
        with self._session() as db:
            row = db.get(self.BlockchainOutbox, event_id)
            if row is None:
                return
            row.status = "SUBMITTED"
            row.tx_hash = tx_hash
            row.updated_at = datetime.now(UTC)
            db.commit()

    def process_blockchain_outbox(self, handler, limit: int = 10) -> None:
        for event in self.claim_blockchain_events(limit):
            try:
                result = handler(event["event_type"], event["payload"])
                if result is False:
                    raise OSError("blockchain operation was rejected")
                self.mark_blockchain_processed(
                    event["id"], result if isinstance(result, str) else None
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                self.mark_blockchain_retry(event["id"], str(exc))

    def record_aggregation(self, update_id: str) -> None:
        """Mark a submitted/verified update as aggregated into the global model."""
        with self._session() as db:
            row = db.get(self.Update, update_id)
            if row is not None:
                row.status = self.UpdateStatus.AGGREGATED
                db.commit()

    def record_rejection(
        self,
        update_id: str,
        client_id: str,
        round_number: int,
        nonce: str,
        artifact_hash: str,
        reason: str,
    ) -> None:
        """Persist rejection metadata only; payloads are never copied to the DB."""
        with self._session() as db:
            round_id = f"{self.federation_id}_round{round_number}"
            row = db.get(self.Update, update_id)
            if row is None:
                row = self.Update(id=update_id, round_id=round_id, client_id=client_id)
                db.add(row)
            row.status = self.UpdateStatus.REJECTED
            row.nonce = nonce
            row.artifact_hash = artifact_hash
            row.rejection_reason = reason[:128]
            db.commit()

    def record_global_model(
        self, round_number: int, uri: str, sha256_hash: str, model_version: str
    ) -> None:
        """Persist the aggregate artifact pointer used for restart validation."""
        with self._session() as db:
            artifact_id = f"{self.federation_id}_global_{round_number}"
            artifact = db.get(self.ModelArtifact, artifact_id)
            if artifact is None:
                artifact = self.ModelArtifact(id=artifact_id, federation_id=self.federation_id)
                db.add(artifact)
            artifact.round_number = round_number
            artifact.client_id = None
            artifact.uri = uri
            artifact.sha256_hash = sha256_hash
            artifact.model_version = model_version
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is not None:
                row.global_model_artifact_id = artifact_id
                row.model_version = model_version
            db.commit()

    def finalize_round(self, round_number: int) -> None:
        with self._session() as db:
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is not None:
                row.status = self.RoundStatus.COMPLETED
                row.finalized_at = datetime.now(UTC)
                db.commit()

    def save_recovery_state(self, round_number: int, state: dict) -> None:
        with self._session() as db:
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is not None:
                row.recovery_state = json.dumps(state, sort_keys=True)
                db.commit()

    def fail_round(self, round_number: int) -> None:
        """Persist a quorum/aggregation failure without falsely finalizing it."""
        with self._session() as db:
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is not None:
                row.status = self.RoundStatus.FAILED
                row.finalized_at = datetime.now(UTC)
                db.commit()

    def restore_state(self) -> dict:
        """Read durable coordinator state so restart does not recreate lifecycle rows."""
        with self._session() as db:
            rounds = (
                db.query(self.Round)
                .filter(self.Round.federation_id == self.federation_id)
                .order_by(self.Round.round_number.desc())
                .all()
            )
            clients = (
                db.query(self.Client).filter(self.Client.federation_id == self.federation_id).all()
            )
            active = next(
                (
                    r
                    for r in rounds
                    if r.status.value
                    in {
                        "ACTIVE",
                        "COLLECTING",
                        "VALIDATING",
                        "AGGREGATING",
                        "COMMITTING",
                        "RECOVERY_REQUIRED",
                    }
                ),
                None,
            )
            latest = rounds[0] if rounds else None
            artifact = None
            if latest and latest.global_model_artifact_id:
                artifact = db.get(self.ModelArtifact, latest.global_model_artifact_id)
            return {
                "current_round": active.round_number
                if active
                else ((latest.round_number + 1) if latest else 0),
                "registered_clients": {
                    c.id: {
                        "status": "ONLINE" if c.is_active else "OFFLINE",
                        "lifecycle": c.lifecycle_status.value,
                        "last_heartbeat": (c.last_seen_at or c.registered_at).timestamp(),
                        "registered_at": c.registered_at.timestamp(),
                        "capabilities": json.loads(c.capabilities or "{}"),
                        "pubkey": c.public_key_b64,
                    }
                    for c in clients
                },
                "model_version": active.model_version
                if active
                else (latest.model_version if latest else None),
                "recovery_state": json.loads(active.recovery_state or "{}") if active else {},
                "global_artifact": (
                    {
                        "uri": artifact.uri,
                        "sha256_hash": artifact.sha256_hash,
                        "model_version": artifact.model_version,
                    }
                    if artifact
                    else None
                ),
            }
