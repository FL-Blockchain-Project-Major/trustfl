import base64
import json
import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Client, ClientLifecycleStatus
from apps.api.api.repositories.clients import ClientRepository
from apps.api.api.repositories.federations import FederationRepository
from apps.api.api.schemas.clients import ClientRegister

logger = logging.getLogger(__name__)


class ClientService:
    def __init__(self, db: Session):
        self.repo = ClientRepository(db)
        self.fed_repo = FederationRepository(db)

    def register(self, payload: ClientRegister) -> Client:
        if not self.fed_repo.get(payload.federation_id):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Federation '{payload.federation_id}' not found"
            )
        if self.repo.get(payload.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Client '{payload.id}' already registered"
            )
        if self.repo.get_by_public_key(payload.public_key_b64):
            raise HTTPException(status.HTTP_409_CONFLICT, "Public key is already enrolled")
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

                raw_key = base64.b64decode(payload.public_key_b64, validate=True)
                Ed25519PublicKey.from_public_bytes(raw_key)
            except (ValueError, TypeError):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Ed25519 public key") from None
        now = datetime.now(UTC)
        production = os.getenv("ENVIRONMENT", "development").lower() == "production"
        lifecycle = (
            ClientLifecycleStatus.PENDING
            if production or os.getenv("CLIENT_ENROLLMENT_AUTO_APPROVE", "true").lower() != "true"
            else ClientLifecycleStatus.ACTIVE
        )
        client = Client(
            id=payload.id,
            federation_id=payload.federation_id,
            public_key_b64=payload.public_key_b64,
            capabilities=json.dumps(payload.capabilities) if payload.capabilities else None,
            lifecycle_status=lifecycle,
            is_active=lifecycle == ClientLifecycleStatus.ACTIVE,
            enrolled_at=now if lifecycle == ClientLifecycleStatus.ACTIVE else None,
            enrollment_id=f"enr_{uuid.uuid4().hex}",
        )
        logger.info("Registering client %s in federation %s", payload.id, payload.federation_id)
        return self.repo.create(client)

    def get_or_404(self, client_id: str) -> Client:
        c = self.repo.get(client_id)
        if not c:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client '{client_id}' not found")
        return c

    def list_by_federation(self, federation_id: str) -> list[Client]:
        return self.repo.get_by_federation(federation_id)

    def heartbeat(self, client_id: str) -> Client:
        c = self.get_or_404(client_id)
        c.last_seen_at = datetime.now(UTC)
        return self.repo.save(c)

    def set_lifecycle(
        self,
        client_id: str,
        lifecycle: ClientLifecycleStatus,
        key_expires_at: datetime | None = None,
    ) -> Client:
        client = self.get_or_404(client_id)
        now = datetime.now(UTC)
        if lifecycle == ClientLifecycleStatus.ACTIVE:
            if client.lifecycle_status == ClientLifecycleStatus.REVOKED:
                raise HTTPException(status.HTTP_409_CONFLICT, "Revoked identities cannot be reactivated")
            client.enrolled_at = client.enrolled_at or now
            client.suspended_at = None
            client.is_active = True
        elif lifecycle == ClientLifecycleStatus.REVOKED:
            client.revoked_at = now
            client.is_active = False
        elif lifecycle == ClientLifecycleStatus.SUSPENDED:
            client.suspended_at = now
            client.is_active = False
        else:
            client.is_active = False
        client.lifecycle_status = lifecycle
        if key_expires_at is not None:
            client.key_expires_at = key_expires_at
        return self.repo.save(client)

    def rotate_public_key(self, client_id: str, public_key_b64: str) -> Client:
        client = self.get_or_404(client_id)
        if client.lifecycle_status == ClientLifecycleStatus.REVOKED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Revoked identities cannot rotate keys")
        if client.public_key_b64 == public_key_b64:
            raise HTTPException(status.HTTP_409_CONFLICT, "New public key must differ from current key")
        client.public_key_b64 = public_key_b64
        client.key_version += 1
        client.is_active = False
        client.lifecycle_status = ClientLifecycleStatus.PENDING
        client.enrolled_at = None
        return self.repo.save(client)
