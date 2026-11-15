import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Client, ModelArtifact
from apps.api.api.repositories.artifacts import ArtifactRepository
from apps.api.api.schemas.artifacts import ArtifactCreate
from apps.api.api.security.auth import AuthContext, require_federation_access

logger = logging.getLogger(__name__)


class ArtifactService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ArtifactRepository(db)

    def create(self, payload: ArtifactCreate, context: AuthContext) -> ModelArtifact:
        require_federation_access(context, payload.federation_id)
        if payload.client_id:
            client = self.db.query(Client).filter(Client.id == payload.client_id).one_or_none()
            if client is None or client.federation_id != payload.federation_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
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

    def list_by_federation(self, federation_id: str, context: AuthContext) -> list[ModelArtifact]:
        require_federation_access(context, federation_id)
        return self.repo.get_by_federation(federation_id)
