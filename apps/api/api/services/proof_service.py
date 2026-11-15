import logging
import os

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.api.db.models import Client, Proof, Round, Update
from apps.api.api.repositories.proofs import ProofRepository
from apps.api.api.schemas.proofs import ProofSubmit
from apps.api.api.security.auth import AuthContext, require_federation_access
from apps.coordinator.zkp_verifier import ZKPVerifier

logger = logging.getLogger(__name__)


class ProofService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProofRepository(db)

    def submit(self, payload: ProofSubmit, context: AuthContext) -> Proof:
        require_federation_access(context, payload.federation_id)
        update = self.db.query(Update).filter(Update.id == payload.update_id).one_or_none()
        round_record = self.db.query(Round).filter(Round.id == payload.round_id).one_or_none()
        client = self.db.query(Client).filter(Client.id == payload.client_id).one_or_none()
        if (
            update is None
            or round_record is None
            or client is None
            or update.client_id != payload.client_id
            or update.round_id != payload.round_id
            or round_record.federation_id != payload.federation_id
            or client.federation_id != payload.federation_id
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        if self.repo.get(payload.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Proof '{payload.id}' already exists")
        if payload.proof is None or payload.public_signals is None:
            if os.getenv("ENVIRONMENT", "development").lower() == "production":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mandatory proof is missing")
        else:
            verifier = ZKPVerifier()
            result = verifier.verify(
                proof=payload.proof,
                public_signals=payload.public_signals,
                expected_signals=[
                    payload.client_id,
                    payload.federation_id,
                    payload.round_id,
                    payload.model_version or "",
                    payload.public_commitment,
                ],
            )
            if not result.valid:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Proof verification failed")
        proof = Proof(
            **payload.model_dump(exclude={"proof", "public_signals"}),
            is_valid=payload.proof is not None,
        )
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
