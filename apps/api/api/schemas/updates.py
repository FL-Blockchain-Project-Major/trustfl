from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from apps.api.api.db.models import UpdateStatus

class UpdateSubmit(BaseModel):
    id: str
    round_id: str
    client_id: str
    artifact_hash: Optional[str] = None
    artifact_id: Optional[str] = None
    nonce: Optional[str] = None
    num_examples: Optional[int] = None
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
