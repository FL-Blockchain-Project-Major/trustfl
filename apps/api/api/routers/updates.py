
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.common import APIResponse
from apps.api.api.schemas.updates import UpdateOut, UpdateStatusChange, UpdateSubmit
from apps.api.api.services.update_service import UpdateService

router = APIRouter(prefix="/updates", tags=["Updates"])

def get_service(db: Session = Depends(get_db)) -> UpdateService:  # noqa: B008
    return UpdateService(db)

@router.post("/", response_model=APIResponse[UpdateOut])
def submit_update(payload: UpdateSubmit, service: UpdateService = Depends(get_service)):  # noqa: B008
    upd = service.submit(payload)
    return APIResponse(data=upd)

@router.get("/round/{round_id}", response_model=APIResponse[list[UpdateOut]])
def list_updates(round_id: str, service: UpdateService = Depends(get_service)):  # noqa: B008
    upds = service.list_by_round(round_id)
    return APIResponse(data=upds)

@router.get("/federation/{federation_id}", response_model=APIResponse[list[UpdateOut]])
def list_federation_updates(
    federation_id: str,
    service: UpdateService = Depends(get_service),  # noqa: B008
):
    return APIResponse(data=service.list_by_federation(federation_id))

@router.put("/{update_id}/status", response_model=APIResponse[UpdateOut])
def update_status(update_id: str, payload: UpdateStatusChange, service: UpdateService = Depends(get_service)):  # noqa: B008
    upd = service.update_status(update_id, payload)
    return APIResponse(data=upd)
