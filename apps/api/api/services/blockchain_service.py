import logging
from datetime import UTC

from sqlalchemy.orm import Session

from apps.api.api.db.models import BlockchainTransaction
from apps.api.api.repositories.blockchain import BlockchainTxRepository

logger = logging.getLogger(__name__)

class BlockchainTxService:
    def __init__(self, db: Session):
        self.repo = BlockchainTxRepository(db)

    def record(self, id: str, contract_name: str, function_name: str,
               entity_id: str = None, entity_type: str = None,
               tx_hash: str = None, status: str = "PENDING",
               error: str = None) -> BlockchainTransaction:
        existing = self.repo.get(id)
        if existing is not None:
            if tx_hash:
                existing.tx_hash = tx_hash
            if status:
                existing.status = status
            if error:
                existing.error_message = error
            if status == "CONFIRMED":
                from datetime import datetime
                existing.confirmed_at = datetime.now(UTC)
            if entity_id:
                existing.entity_id = entity_id
            if entity_type:
                existing.entity_type = entity_type
            return self.repo.save(existing)
        tx = BlockchainTransaction(
            id=id, tx_hash=tx_hash, contract_name=contract_name,
            function_name=function_name, status=status,
            entity_id=entity_id, entity_type=entity_type,
            error_message=error,
        )
        if status == "CONFIRMED":
            from datetime import datetime
            tx.confirmed_at = datetime.now(UTC)
        logger.info("Recording blockchain tx %s (%s.%s)", id, contract_name, function_name)
        return self.repo.create(tx)

    def get_or_404(self, tx_id: str) -> BlockchainTransaction:
        from fastapi import HTTPException
        from fastapi import status as http_status
        t = self.repo.get(tx_id)
        if not t:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, f"Transaction '{tx_id}' not found")
        return t

    def list_all(self, skip: int = 0, limit: int = 100) -> list[BlockchainTransaction]:
        return self.repo.get_all(skip=skip, limit=limit)

    def list_by_entity(self, entity_id: str) -> list[BlockchainTransaction]:
        return self.repo.get_by_entity(entity_id)

    def confirm(self, tx_id: str, tx_hash: str) -> BlockchainTransaction:
        from datetime import datetime
        t = self.get_or_404(tx_id)
        t.tx_hash = tx_hash
        t.status = "CONFIRMED"
        t.confirmed_at = datetime.now(UTC)
        return self.repo.save(t)

    def fail(self, tx_id: str, error: str) -> BlockchainTransaction:
        t = self.get_or_404(tx_id)
        t.status = "FAILED"
        t.error_message = error
        return self.repo.save(t)
