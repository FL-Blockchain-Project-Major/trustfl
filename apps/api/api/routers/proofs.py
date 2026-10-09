from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.common import APIResponse
from apps.api.api.schemas.proofs import ProofOut, ProofSubmit
from apps.api.api.services.proof_service import ProofService

router = APIRouter(prefix="/proofs", tags=["Proofs"])


def get_service(db: Session = Depends(get_db)) -> ProofService:  # noqa: B008
    return ProofService(db)


@router.post("/", response_model=APIResponse[ProofOut])
def submit_proof(payload: ProofSubmit, service: ProofService = Depends(get_service)):  # noqa: B008
    p = service.submit(payload)
    return APIResponse(data=p)


@router.get("/update/{update_id}", response_model=APIResponse[list[ProofOut]])
def list_proofs(update_id: str, service: ProofService = Depends(get_service)):  # noqa: B008
    p = service.list_by_update(update_id)
    return APIResponse(data=p)


@router.get("/{proof_id}", response_model=APIResponse[ProofOut])
def get_proof(proof_id: str, service: ProofService = Depends(get_service)):  # noqa: B008
    return APIResponse(data=service.get_or_404(proof_id))
