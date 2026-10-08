from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.api.db.session import get_db
from apps.api.api.schemas.updates import UpdateSubmit, UpdateStatusChange, UpdateOut
from apps.api.api.services.update_service import UpdateService
from apps.api.api.schemas.common import APIResponse

router = APIRouter(prefix="/updates", tags=["Updates"])

def get_service(db: Session = Depends(get_db)) -> UpdateService:
    return UpdateService(db)

@router.post("/", response_model=APIResponse[UpdateOut])
def submit_update(payload: UpdateSubmit, service: UpdateService = Depends(get_service)):
    upd = service.submit(payload)
    return APIResponse(data=upd)

@router.get("/round/{round_id}", response_model=APIResponse[List[UpdateOut]])
def list_updates(round_id: str, service: UpdateService = Depends(get_service)):
    upds = service.list_by_round(round_id)
    return APIResponse(data=upds)

@router.put("/{update_id}/status", response_model=APIResponse[UpdateOut])
def update_status(update_id: str, payload: UpdateStatusChange, service: UpdateService = Depends(get_service)):
    upd = service.update_status(update_id, payload)
    return APIResponse(data=upd)
