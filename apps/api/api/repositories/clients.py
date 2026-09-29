from typing import List
from apps.api.api.db.models import Client
from .base import BaseRepository

class ClientRepository(BaseRepository[Client]):
    model = Client

    def get_by_federation(self, federation_id: str) -> List[Client]:
        return self.db.query(Client).filter(Client.federation_id == federation_id).all()

    def get_active_by_federation(self, federation_id: str) -> List[Client]:
        return self.db.query(Client).filter(
            Client.federation_id == federation_id,
            Client.is_active == True
        ).all()
