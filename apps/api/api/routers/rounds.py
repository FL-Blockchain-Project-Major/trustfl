from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.api.db.session import get_db
from apps.api.api.schemas.rounds import RoundCreate, RoundStatusUpdate, RoundOut
from apps.api.api.services.round_service import RoundService
from apps.api.api.schemas.common import APIResponse

router = APIRouter(prefix="/rounds", tags=["Rounds"])

def get_service(db: Session = Depends(get_db)) -> RoundService:
    return RoundService(db)

@router.post("/", response_model=APIResponse[RoundOut])
def create_round(payload: RoundCreate, service: RoundService = Depends(get_service)):
    rnd = service.create(payload)
    return APIResponse(data=rnd)

@router.get("/federation/{federation_id}", response_model=APIResponse[List[RoundOut]])
def list_rounds(federation_id: str, service: RoundService = Depends(get_service)):
    rnds = service.list_by_federation(federation_id)
    return APIResponse(data=rnds)

@router.put("/{round_id}/status", response_model=APIResponse[RoundOut])
def update_round_status(round_id: str, payload: RoundStatusUpdate, service: RoundService = Depends(get_service)):
    rnd = service.update_status(round_id, payload)
    return APIResponse(data=rnd)
