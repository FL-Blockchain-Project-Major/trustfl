from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.api.db.session import get_db
from apps.api.api.schemas.proofs import ProofSubmit, ProofOut
from apps.api.api.services.proof_service import ProofService
from apps.api.api.schemas.common import APIResponse

router = APIRouter(prefix="/proofs", tags=["Proofs"])

def get_service(db: Session = Depends(get_db)) -> ProofService:
    return ProofService(db)

@router.post("/", response_model=APIResponse[ProofOut])
def submit_proof(payload: ProofSubmit, service: ProofService = Depends(get_service)):
    p = service.submit(payload)
    return APIResponse(data=p)

@router.get("/update/{update_id}", response_model=APIResponse[List[ProofOut]])
def list_proofs(update_id: str, service: ProofService = Depends(get_service)):
    p = service.list_by_update(update_id)
    return APIResponse(data=p)
