"""Coordinator persistence adapter for the API control-plane database."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class CoordinatorPersistence:
    """Write coordinator lifecycle events to the API's SQLAlchemy models.

    The coordinator remains usable in unit tests without this adapter. In a
    deployed stack the adapter is created by the coordinator process and uses
    the same DATABASE_URL as the API.
    """

    def __init__(self) -> None:
        from apps.api.api.db.models import (
            Client,
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
        self.federation_id = os.getenv("FL_FEDERATION_ID", "fed-default")

    def _session(self):
        return self.SessionLocal()

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
                row = self.Client(
                    id=client_id,
                    federation_id=self.federation_id,
                    public_key_b64=public_key,
                )
                db.add(row)
            row.public_key_b64 = public_key
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
            row.status = self.RoundStatus.ACTIVE
            row.model_version = model_version
            row.started_at = datetime.now(UTC)
            db.commit()

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
    ) -> None:
        with self._session() as db:
            round_id = f"{self.federation_id}_round{round_number}"
            row = db.get(self.Update, update_id)
            if row is None:
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
                row.status = self.RoundStatus.FINALIZED
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
            active = next((r for r in rounds if r.status == self.RoundStatus.ACTIVE), None)
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
