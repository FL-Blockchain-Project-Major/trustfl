
from apps.api.api.db.models import ModelArtifact

from .base import BaseRepository


class ArtifactRepository(BaseRepository[ModelArtifact]):
    model = ModelArtifact

    def get_by_federation(self, federation_id: str) -> list[ModelArtifact]:
        return self.db.query(ModelArtifact).filter(ModelArtifact.federation_id == federation_id).all()
