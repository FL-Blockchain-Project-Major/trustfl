from apps.api.api.db.models import Round, Update

from .base import BaseRepository


class UpdateRepository(BaseRepository[Update]):
    model = Update

    def get_by_round(self, round_id: str) -> list[Update]:
        return self.db.query(Update).filter(Update.round_id == round_id).all()

    def get_by_federation(self, federation_id: str) -> list[Update]:
        return (
            self.db.query(Update)
            .join(Round, Round.id == Update.round_id)
            .filter(Round.federation_id == federation_id)
            .all()
        )

    def get_by_client_and_round(self, client_id: str, round_id: str) -> list[Update]:
        return (
            self.db.query(Update)
            .filter(Update.client_id == client_id, Update.round_id == round_id)
            .all()
        )
