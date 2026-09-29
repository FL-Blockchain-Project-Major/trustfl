from typing import List, Optional
from apps.api.api.db.models import Round, RoundStatus
from .base import BaseRepository

class RoundRepository(BaseRepository[Round]):
    model = Round

    def get_by_federation(self, federation_id: str) -> List[Round]:
        return self.db.query(Round).filter(Round.federation_id == federation_id).order_by(Round.round_number).all()

    def get_active_round(self, federation_id: str) -> Optional[Round]:
        return self.db.query(Round).filter(
            Round.federation_id == federation_id,
            Round.status == RoundStatus.ACTIVE
        ).first()
