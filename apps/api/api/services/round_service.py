import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Round, RoundStatus
from apps.api.api.repositories.federations import FederationRepository
from apps.api.api.repositories.rounds import RoundRepository
from apps.api.api.schemas.rounds import RoundCreate, RoundStatusUpdate

logger = logging.getLogger(__name__)

class RoundService:
    def __init__(self, db: Session):
        self.repo = RoundRepository(db)
        self.fed_repo = FederationRepository(db)

    def create(self, payload: RoundCreate) -> Round:
        if not self.fed_repo.get(payload.federation_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Federation '{payload.federation_id}' not found")
        round_id = f"{payload.federation_id}_round{payload.round_number}"
        if self.repo.get(round_id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Round {round_id} already exists")
        rnd = Round(
            id=round_id,
            federation_id=payload.federation_id,
            round_number=payload.round_number,
            model_version=payload.model_version,
            started_at=datetime.now(UTC),
            status=RoundStatus.CREATED,
        )
        logger.info("Creating round %s", round_id)
        return self.repo.create(rnd)

    def get_or_404(self, round_id: str) -> Round:
        r = self.repo.get(round_id)
        if not r:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Round '{round_id}' not found")
        return r

    def list_by_federation(self, federation_id: str) -> list[Round]:
        return self.repo.get_by_federation(federation_id)

    def update_status(self, round_id: str, payload: RoundStatusUpdate) -> Round:
        rnd = self.get_or_404(round_id)
        rnd.status = payload.status
        if payload.global_model_artifact_id:
            rnd.global_model_artifact_id = payload.global_model_artifact_id
        if payload.status == RoundStatus.FINALIZED:
            rnd.finalized_at = datetime.now(UTC)
        logger.info("Updating round %s to status %s", round_id, payload.status)
        return self.repo.save(rnd)
