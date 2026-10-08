from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.api.api.db.models import UpdateStatus


class UpdateSubmit(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    round_id: str = Field(..., min_length=1, max_length=128)
    client_id: str = Field(..., min_length=1, max_length=64)
    artifact_hash: str | None = Field(default=None, max_length=128)
    artifact_id: str | None = Field(default=None, max_length=128)
    nonce: str | None = Field(default=None, max_length=128)
    num_examples: int | None = Field(default=None, ge=1)
    loss: float | None = None


class UpdateStatusChange(BaseModel):
    status: UpdateStatus
    verified_at: datetime | None = None


class UpdateOut(BaseModel):
    id: str
    round_id: str
    client_id: str
    status: UpdateStatus
    artifact_id: str | None
    artifact_hash: str | None
    nonce: str | None
    num_examples: int | None
    loss: float | None
    submitted_at: datetime
    verified_at: datetime | None
    model_config = {"from_attributes": True}
