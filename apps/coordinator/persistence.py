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
        self.federation_id = os.getenv("FL_FEDERATION_ID", "default")

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
            row.status = self.UpdateStatus.VERIFIED
            row.artifact_hash = artifact_hash
            row.artifact_id = update_id
            row.num_examples = num_examples
            row.loss = metrics.get("loss")
            row.nonce = nonce
            row.verified_at = datetime.now(UTC)
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

    def finalize_round(self, round_number: int) -> None:
        with self._session() as db:
            row = db.get(self.Round, f"{self.federation_id}_round{round_number}")
            if row is not None:
                row.status = self.RoundStatus.FINALIZED
                row.finalized_at = datetime.now(UTC)
                db.commit()

