import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Federation
from apps.api.api.repositories.federations import FederationRepository
from apps.api.api.schemas.federations import FederationCreate, FederationUpdate

logger = logging.getLogger(__name__)


class FederationService:
    def __init__(self, db: Session):
        self.repo = FederationRepository(db)

    def create(self, payload: FederationCreate) -> Federation:
        if self.repo.get(payload.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Federation '{payload.id}' already exists"
            )
        fed = Federation(**payload.model_dump())
        logger.info("Creating federation %s", payload.id)
        return self.repo.create(fed)

    def get_or_404(self, federation_id: str) -> Federation:
        fed = self.repo.get(federation_id)
        if not fed:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Federation '{federation_id}' not found"
            )
        return fed

    def list_all(self, skip: int = 0, limit: int = 100) -> list[Federation]:
        return self.repo.get_all(skip=skip, limit=limit)

    def update(self, federation_id: str, payload: FederationUpdate) -> Federation:
        fed = self.get_or_404(federation_id)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(fed, field, value)
        fed.updated_at = datetime.now(UTC)
        logger.info("Updating federation %s", federation_id)
        return self.repo.save(fed)

    def delete(self, federation_id: str) -> None:
        fed = self.get_or_404(federation_id)
        logger.info("Deleting federation %s", federation_id)
        self.repo.delete(fed)
