import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import ModelArtifact
from apps.api.api.repositories.artifacts import ArtifactRepository
from apps.api.api.schemas.artifacts import ArtifactCreate

logger = logging.getLogger(__name__)


class ArtifactService:
    def __init__(self, db: Session):
        self.repo = ArtifactRepository(db)

    def create(self, payload: ArtifactCreate) -> ModelArtifact:
        if self.repo.get(payload.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Artifact '{payload.id}' already exists")
        artifact = ModelArtifact(**payload.model_dump())
        logger.info("Recording artifact %s", payload.id)
        return self.repo.create(artifact)

    def get_or_404(self, artifact_id: str) -> ModelArtifact:
        a = self.repo.get(artifact_id)
        if not a:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Artifact '{artifact_id}' not found")
        return a

    def list_by_federation(self, federation_id: str) -> list[ModelArtifact]:
        return self.repo.get_by_federation(federation_id)
