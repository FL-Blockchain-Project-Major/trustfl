from apps.api.api.db.models import Client

from .base import BaseRepository


class ClientRepository(BaseRepository[Client]):
    model = Client

    def get_by_federation(self, federation_id: str) -> list[Client]:
        return self.db.query(Client).filter(Client.federation_id == federation_id).all()

    def get_active_by_federation(self, federation_id: str) -> list[Client]:
        return (
            self.db.query(Client)
            .filter(
                Client.federation_id == federation_id,
                Client.is_active,
                Client.lifecycle_status == "ACTIVE",
            )
            .all()
        )

    def get_by_public_key(self, public_key_b64: str) -> Client | None:
        return self.db.query(Client).filter(Client.public_key_b64 == public_key_b64).first()
