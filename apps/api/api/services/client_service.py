import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Client
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
        client = Client(
            id=payload.id,
            federation_id=payload.federation_id,
            public_key_b64=payload.public_key_b64,
            capabilities=json.dumps(payload.capabilities) if payload.capabilities else None,
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
