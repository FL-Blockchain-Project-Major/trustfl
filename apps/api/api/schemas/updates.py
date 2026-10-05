from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from apps.api.api.db.models import UpdateStatus


class UpdateSubmit(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    round_id: str = Field(..., min_length=1, max_length=128)
    client_id: str = Field(..., min_length=1, max_length=64)
    artifact_hash: Optional[str] = Field(default=None, max_length=128)
    artifact_id: Optional[str] = Field(default=None, max_length=128)
    nonce: Optional[str] = Field(default=None, max_length=128)
    num_examples: Optional[int] = Field(default=None, ge=1)
    loss: Optional[float] = None


class UpdateStatusChange(BaseModel):
    status: UpdateStatus
    verified_at: Optional[datetime] = None


class UpdateOut(BaseModel):
    id: str
    round_id: str
    client_id: str
    status: UpdateStatus
    artifact_id: Optional[str]
    artifact_hash: Optional[str]
    nonce: Optional[str]
    num_examples: Optional[int]
    loss: Optional[float]
    submitted_at: datetime
    verified_at: Optional[datetime]
    model_config = {"from_attributes": True}
