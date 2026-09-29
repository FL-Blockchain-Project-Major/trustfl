import logging
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from apps.api.api.db.models import Update, UpdateStatus
from apps.api.api.repositories.updates import UpdateRepository
from apps.api.api.schemas.updates import UpdateSubmit, UpdateStatusChange

logger = logging.getLogger(__name__)

class UpdateService:
    def __init__(self, db: Session):
        self.repo = UpdateRepository(db)

    def submit(self, payload: UpdateSubmit) -> Update:
        if self.repo.get(payload.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Update '{payload.id}' already submitted")
        upd = Update(
            id=payload.id, round_id=payload.round_id, client_id=payload.client_id,
            artifact_hash=payload.artifact_hash, artifact_id=payload.artifact_id,
            nonce=payload.nonce, num_examples=payload.num_examples, loss=payload.loss,
        )
        logger.info("Submitting update %s from client %s", payload.id, payload.client_id)
        return self.repo.create(upd)

    def get_or_404(self, update_id: str) -> Update:
        u = self.repo.get(update_id)
        if not u:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Update '{update_id}' not found")
        return u

    def list_by_round(self, round_id: str) -> List[Update]:
        return self.repo.get_by_round(round_id)

    def update_status(self, update_id: str, payload: UpdateStatusChange) -> Update:
        upd = self.get_or_404(update_id)
        upd.status = payload.status
        if payload.verified_at:
            upd.verified_at = payload.verified_at
        elif payload.status == UpdateStatus.VERIFIED:
            upd.verified_at = datetime.now(timezone.utc)
        logger.info("Updating update %s to status %s", update_id, payload.status)
        return self.repo.save(upd)
