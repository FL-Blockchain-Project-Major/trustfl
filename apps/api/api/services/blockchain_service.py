import logging
from typing import List
from sqlalchemy.orm import Session
from apps.api.api.db.models import BlockchainTransaction
from apps.api.api.repositories.blockchain import BlockchainTxRepository

logger = logging.getLogger(__name__)

class BlockchainTxService:
    def __init__(self, db: Session):
        self.repo = BlockchainTxRepository(db)

    def record(self, id: str, contract_name: str, function_name: str,
               entity_id: str = None, entity_type: str = None,
               tx_hash: str = None, status: str = "PENDING") -> BlockchainTransaction:
        tx = BlockchainTransaction(
            id=id, tx_hash=tx_hash, contract_name=contract_name,
            function_name=function_name, status=status,
            entity_id=entity_id, entity_type=entity_type,
        )
        logger.info("Recording blockchain tx %s (%s.%s)", id, contract_name, function_name)
        return self.repo.create(tx)

    def get_or_404(self, tx_id: str) -> BlockchainTransaction:
        from fastapi import HTTPException, status as http_status
        t = self.repo.get(tx_id)
        if not t:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Transaction '{tx_id}' not found")
        return t

    def list_all(self, skip: int = 0, limit: int = 100) -> List[BlockchainTransaction]:
        return self.repo.get_all(skip=skip, limit=limit)

    def list_by_entity(self, entity_id: str) -> List[BlockchainTransaction]:
        return self.repo.get_by_entity(entity_id)

    def confirm(self, tx_id: str, tx_hash: str) -> BlockchainTransaction:
        from datetime import datetime, timezone
        t = self.get_or_404(tx_id)
        t.tx_hash = tx_hash
        t.status = "CONFIRMED"
        t.confirmed_at = datetime.now(timezone.utc)
        return self.repo.save(t)

    def fail(self, tx_id: str, error: str) -> BlockchainTransaction:
        t = self.get_or_404(tx_id)
        t.status = "FAILED"
        t.error_message = error
        return self.repo.save(t)
