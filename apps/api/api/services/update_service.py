"""
Update submission service with:
- Duplicate ID rejection (409)
- Duplicate client+round submission rejection (400)
- Nonce replay detection (400)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Update, UpdateStatus
from apps.api.api.repositories.updates import UpdateRepository
from apps.api.api.schemas.updates import UpdateStatusChange, UpdateSubmit

logger = logging.getLogger(__name__)


class UpdateService:
    def __init__(self, db: Session):
        self.repo = UpdateRepository(db)

    def submit(self, payload: UpdateSubmit) -> Update:
        # 1. Reject duplicate update ID
        if self.repo.get(payload.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Update '{payload.id}' already submitted")

        # 2. Reject a second update from the same client in the same round
        existing = self.repo.get_by_client_and_round(payload.client_id, payload.round_id)
        if existing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Client already submitted an update for round '{payload.round_id}'",
            )

        # 3. Reject nonce replay within the round
        if payload.nonce:
            round_updates = self.repo.get_by_round(payload.round_id)
            used_nonces = {u.nonce for u in round_updates if u.nonce}
            if payload.nonce in used_nonces:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Nonce already used in round '{payload.round_id}'",
                )

        upd = Update(
            id=payload.id,
            round_id=payload.round_id,
            client_id=payload.client_id,
            artifact_hash=payload.artifact_hash,
            artifact_id=payload.artifact_id,
            nonce=payload.nonce,
            num_examples=payload.num_examples,
            loss=payload.loss,
        )
        logger.info("Submitting update %s from client %s", payload.id, payload.client_id)
        return self.repo.create(upd)

    def get_or_404(self, update_id: str) -> Update:
        u = self.repo.get(update_id)
        if not u:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Update '{update_id}' not found")
        return u

    def list_by_round(self, round_id: str) -> list[Update]:
        return self.repo.get_by_round(round_id)

    def update_status(self, update_id: str, payload: UpdateStatusChange) -> Update:
        upd = self.get_or_404(update_id)
        upd.status = payload.status
        if payload.verified_at:
            upd.verified_at = payload.verified_at
        elif payload.status == UpdateStatus.VERIFIED:
            upd.verified_at = datetime.now(UTC)
        logger.info("Updating update %s to status %s", update_id, payload.status)
        return self.repo.save(upd)
