from typing import List
from apps.api.api.db.models import BlockchainTransaction
from .base import BaseRepository

class BlockchainTxRepository(BaseRepository[BlockchainTransaction]):
    model = BlockchainTransaction

    def get_by_entity(self, entity_id: str) -> List[BlockchainTransaction]:
        return self.db.query(BlockchainTransaction).filter(
            BlockchainTransaction.entity_id == entity_id
        ).all()

    def get_by_status(self, status: str) -> List[BlockchainTransaction]:
        return self.db.query(BlockchainTransaction).filter(
            BlockchainTransaction.status == status
        ).all()
