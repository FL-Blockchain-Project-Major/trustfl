from typing import List
from apps.api.api.db.models import Federation
from .base import BaseRepository

class FederationRepository(BaseRepository[Federation]):
    model = Federation

    def get_by_status(self, status: str) -> List[Federation]:
        return self.db.query(Federation).filter(Federation.status == status).all()
