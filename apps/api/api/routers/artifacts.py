from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.artifacts import ArtifactCreate, ArtifactOut
from apps.api.api.schemas.common import APIResponse
from apps.api.api.security.auth import AuthContext, require_permission
from apps.api.api.services.artifact_service import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


def get_service(db: Session = Depends(get_db)) -> ArtifactService:  # noqa: B008
    return ArtifactService(db)


@router.post("/", response_model=APIResponse[ArtifactOut])
def record_artifact(
    payload: ArtifactCreate,
    context: AuthContext = Depends(require_permission("write")),  # noqa: B008
    service: ArtifactService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    a = service.create(payload, context)
    return APIResponse(data=a)


@router.get("/federation/{federation_id}", response_model=APIResponse[list[ArtifactOut]])
def list_artifacts(
    federation_id: str,
    context: AuthContext = Depends(require_permission("read")),  # noqa: B008
    service: ArtifactService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    a = service.list_by_federation(federation_id, context)
    return APIResponse(data=a)


@router.get(
    "/{artifact_id}",
    response_model=APIResponse[ArtifactOut],
    dependencies=[Depends(require_permission("admin"))],
)
def get_artifact(artifact_id: str, service: ArtifactService = Depends(get_service)):  # noqa: B008
    return APIResponse(data=service.get_or_404(artifact_id))
