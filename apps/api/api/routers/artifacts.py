from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.api.db.session import get_db
from apps.api.api.schemas.artifacts import ArtifactCreate, ArtifactOut
from apps.api.api.services.artifact_service import ArtifactService
from apps.api.api.schemas.common import APIResponse

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

def get_service(db: Session = Depends(get_db)) -> ArtifactService:
    return ArtifactService(db)

@router.post("/", response_model=APIResponse[ArtifactOut])
def record_artifact(payload: ArtifactCreate, service: ArtifactService = Depends(get_service)):
    a = service.create(payload)
    return APIResponse(data=a)

@router.get("/federation/{federation_id}", response_model=APIResponse[List[ArtifactOut]])
def list_artifacts(federation_id: str, service: ArtifactService = Depends(get_service)):
    a = service.list_by_federation(federation_id)
    return APIResponse(data=a)
