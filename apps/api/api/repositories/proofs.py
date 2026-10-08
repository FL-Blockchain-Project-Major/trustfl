
from apps.api.api.db.models import Proof

from .base import BaseRepository


class ProofRepository(BaseRepository[Proof]):
    model = Proof

    def get_by_update(self, update_id: str) -> list[Proof]:
        return self.db.query(Proof).filter(Proof.update_id == update_id).all()

    def get_by_federation(self, federation_id: str) -> list[Proof]:
        return self.db.query(Proof).filter(Proof.federation_id == federation_id).all()
