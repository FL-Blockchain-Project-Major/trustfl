import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.clients import (
    ClientKeyRotation,
    ClientLifecycleUpdate,
    ClientOut,
    ClientRegister,
)
from apps.api.api.schemas.common import APIResponse
from apps.api.api.security.auth import AuthContext, require_permission
from apps.api.api.services.client_service import ClientService

router = APIRouter(prefix="/clients", tags=["Clients"])


def require_admin(request: Request) -> None:
    """Require the dedicated administrative credential for lifecycle operations."""
    expected = os.getenv("API_ADMIN_KEY", "")
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator authorization required")


def get_service(db: Session = Depends(get_db)) -> ClientService:  # noqa: B008
    return ClientService(db)


@router.post("/", response_model=APIResponse[ClientOut])
def register_client(
    payload: ClientRegister,
    context: AuthContext = Depends(require_permission("write")),  # noqa: B008
    service: ClientService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    client = service.register(payload, context)
    return APIResponse(data=ClientOut.from_orm_with_caps(client))


@router.get("/federation/{federation_id}", response_model=APIResponse[list[ClientOut]])
def list_federation_clients(
    federation_id: str,
    context: AuthContext = Depends(require_permission("read")),  # noqa: B008
    service: ClientService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    clients = service.list_by_federation(federation_id, context)
    return APIResponse(data=[ClientOut.from_orm_with_caps(c) for c in clients])


@router.put(
    "/{client_id}/lifecycle",
    response_model=APIResponse[ClientOut],
    dependencies=[Depends(require_admin)],
)
def update_client_lifecycle(
    client_id: str,
    payload: ClientLifecycleUpdate,
    service: ClientService = Depends(get_service),  # noqa: B008
):
    client = service.set_lifecycle(client_id, payload.status, payload.key_expires_at)
    return APIResponse(data=ClientOut.from_orm_with_caps(client))


@router.put(
    "/{client_id}/key",
    response_model=APIResponse[ClientOut],
    dependencies=[Depends(require_admin)],
)
def rotate_client_key(
    client_id: str,
    payload: ClientKeyRotation,
    service: ClientService = Depends(get_service),  # noqa: B008
):
    client = service.rotate_public_key(client_id, payload.public_key_b64)
    return APIResponse(data=ClientOut.from_orm_with_caps(client))
