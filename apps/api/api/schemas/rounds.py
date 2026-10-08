from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.api.api.db.models import RoundStatus


class RoundCreate(BaseModel):
    federation_id: str
    round_number: int = Field(..., ge=1)
    model_version: str | None = None

class RoundStatusUpdate(BaseModel):
    status: RoundStatus
    global_model_artifact_id: str | None = None

class RoundOut(BaseModel):
    id: str
    federation_id: str
    round_number: int
    status: RoundStatus
    model_version: str | None
    global_model_artifact_id: str | None
    started_at: datetime | None
    finalized_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}
