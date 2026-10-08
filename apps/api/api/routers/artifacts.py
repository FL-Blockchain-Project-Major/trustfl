
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.artifacts import ArtifactCreate, ArtifactOut
from apps.api.api.schemas.common import APIResponse
from apps.api.api.services.artifact_service import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

def get_service(db: Session = Depends(get_db)) -> ArtifactService:  # noqa: B008
    return ArtifactService(db)

@router.post("/", response_model=APIResponse[ArtifactOut])
def record_artifact(payload: ArtifactCreate, service: ArtifactService = Depends(get_service)):  # noqa: B008
    a = service.create(payload)
    return APIResponse(data=a)

@router.get("/federation/{federation_id}", response_model=APIResponse[list[ArtifactOut]])
def list_artifacts(federation_id: str, service: ArtifactService = Depends(get_service)):  # noqa: B008
    a = service.list_by_federation(federation_id)
    return APIResponse(data=a)

@router.get("/{artifact_id}", response_model=APIResponse[ArtifactOut])
def get_artifact(artifact_id: str, service: ArtifactService = Depends(get_service)):  # noqa: B008
    return APIResponse(data=service.get_or_404(artifact_id))
