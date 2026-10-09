from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.common import APIResponse
from apps.api.api.schemas.federations import FederationCreate, FederationOut
from apps.api.api.services.federation_service import FederationService

router = APIRouter(prefix="/federations", tags=["Federations"])


def get_service(db: Session = Depends(get_db)) -> FederationService:  # noqa: B008
    return FederationService(db)


@router.post("/", response_model=APIResponse[FederationOut])
def create_federation(payload: FederationCreate, service: FederationService = Depends(get_service)):  # noqa: B008
    fed = service.create(payload)
    return APIResponse(data=fed)


@router.get("/", response_model=APIResponse[list[FederationOut]])
def list_federations(
    skip: int = 0,
    limit: int = 100,
    service: FederationService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    feds = service.list_all(skip=skip, limit=limit)
    return APIResponse(data=feds)


@router.get("/{federation_id}", response_model=APIResponse[FederationOut])
def get_federation(federation_id: str, service: FederationService = Depends(get_service)):  # noqa: B008
    fed = service.get_or_404(federation_id)
    return APIResponse(data=fed)
