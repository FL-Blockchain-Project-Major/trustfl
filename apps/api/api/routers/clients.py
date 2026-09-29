from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.api.db.session import get_db
from apps.api.api.schemas.clients import ClientRegister, ClientOut
from apps.api.api.services.client_service import ClientService
from apps.api.api.schemas.common import APIResponse

router = APIRouter(prefix="/clients", tags=["Clients"])

def get_service(db: Session = Depends(get_db)) -> ClientService:
    return ClientService(db)

@router.post("/", response_model=APIResponse[ClientOut])
def register_client(payload: ClientRegister, service: ClientService = Depends(get_service)):
    client = service.register(payload)
    return APIResponse(data=ClientOut.from_orm_with_caps(client))

@router.get("/federation/{federation_id}", response_model=APIResponse[List[ClientOut]])
def list_federation_clients(federation_id: str, service: ClientService = Depends(get_service)):
    clients = service.list_by_federation(federation_id)
    return APIResponse(data=[ClientOut.from_orm_with_caps(c) for c in clients])
