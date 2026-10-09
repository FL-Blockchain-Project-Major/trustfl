from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.clients import ClientOut, ClientRegister
from apps.api.api.schemas.common import APIResponse
from apps.api.api.services.client_service import ClientService

router = APIRouter(prefix="/clients", tags=["Clients"])


def get_service(db: Session = Depends(get_db)) -> ClientService:  # noqa: B008
    return ClientService(db)


@router.post("/", response_model=APIResponse[ClientOut])
def register_client(payload: ClientRegister, service: ClientService = Depends(get_service)):  # noqa: B008
    client = service.register(payload)
    return APIResponse(data=ClientOut.from_orm_with_caps(client))


@router.get("/federation/{federation_id}", response_model=APIResponse[list[ClientOut]])
def list_federation_clients(federation_id: str, service: ClientService = Depends(get_service)):  # noqa: B008
    clients = service.list_by_federation(federation_id)
    return APIResponse(data=[ClientOut.from_orm_with_caps(c) for c in clients])
