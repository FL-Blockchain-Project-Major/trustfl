from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.common import APIResponse
from apps.api.api.schemas.updates import UpdateOut, UpdateStatusChange, UpdateSubmit
from apps.api.api.security.auth import AuthContext, require_permission
from apps.api.api.services.update_service import UpdateService

router = APIRouter(prefix="/updates", tags=["Updates"])


def get_service(db: Session = Depends(get_db)) -> UpdateService:  # noqa: B008
    return UpdateService(db)


@router.post("/", response_model=APIResponse[UpdateOut])
def submit_update(
    payload: UpdateSubmit,
    context: AuthContext = Depends(require_permission("write")),  # noqa: B008
    service: UpdateService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    upd = service.submit(payload, context)
    return APIResponse(data=upd)


@router.get(
    "/round/{round_id}",
    response_model=APIResponse[list[UpdateOut]],
    dependencies=[Depends(require_permission("admin"))],
)
def list_updates(round_id: str, service: UpdateService = Depends(get_service)):  # noqa: B008
    upds = service.list_by_round(round_id)
    return APIResponse(data=upds)


@router.get(
    "/federation/{federation_id}",
    response_model=APIResponse[list[UpdateOut]],
    dependencies=[Depends(require_permission("read"))],
)
def list_federation_updates(
    federation_id: str,
    service: UpdateService = Depends(get_service),  # noqa: B008
):
    return APIResponse(data=service.list_by_federation(federation_id))


@router.put(
    "/{update_id}/status",
    response_model=APIResponse[UpdateOut],
    dependencies=[Depends(require_permission("admin"))],
)
def update_status(
    update_id: str,
    payload: UpdateStatusChange,
    service: UpdateService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    upd = service.update_status(update_id, payload)
    return APIResponse(data=upd)
