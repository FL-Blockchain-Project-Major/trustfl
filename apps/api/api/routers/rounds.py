from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.common import APIResponse
from apps.api.api.schemas.rounds import RoundCreate, RoundOut, RoundStatusUpdate
from apps.api.api.services.round_service import RoundService

router = APIRouter(prefix="/rounds", tags=["Rounds"])


def get_service(db: Session = Depends(get_db)) -> RoundService:  # noqa: B008
    return RoundService(db)


@router.post("/", response_model=APIResponse[RoundOut])
def create_round(payload: RoundCreate, service: RoundService = Depends(get_service)):  # noqa: B008
    rnd = service.create(payload)
    return APIResponse(data=rnd)


@router.get("/federation/{federation_id}", response_model=APIResponse[list[RoundOut]])
def list_rounds(federation_id: str, service: RoundService = Depends(get_service)):  # noqa: B008
    rnds = service.list_by_federation(federation_id)
    return APIResponse(data=rnds)


@router.put("/{round_id}/status", response_model=APIResponse[RoundOut])
def update_round_status(
    round_id: str,
    payload: RoundStatusUpdate,
    service: RoundService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    rnd = service.update_status(round_id, payload)
    return APIResponse(data=rnd)
