import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Proof
from apps.api.api.repositories.proofs import ProofRepository
from apps.api.api.schemas.proofs import ProofSubmit

logger = logging.getLogger(__name__)

class ProofService:
    def __init__(self, db: Session):
        self.repo = ProofRepository(db)

    def submit(self, payload: ProofSubmit) -> Proof:
        if self.repo.get(payload.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Proof '{payload.id}' already exists")
        proof = Proof(**payload.model_dump())
        logger.info("Recording proof %s for update %s", payload.id, payload.update_id)
        return self.repo.create(proof)

    def get_or_404(self, proof_id: str) -> Proof:
        p = self.repo.get(proof_id)
        if not p:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Proof '{proof_id}' not found")
        return p

    def list_by_update(self, update_id: str) -> list[Proof]:
        return self.repo.get_by_update(update_id)

    def set_validity(self, proof_id: str, is_valid: bool) -> Proof:
        p = self.get_or_404(proof_id)
        p.is_valid = is_valid
        logger.info("Setting proof %s validity to %s", proof_id, is_valid)
        return self.repo.save(p)
