from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from apps.api.api.db.models import FederationStatus

class FederationCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    min_clients: int = Field(default=2, ge=1)
    max_rounds: int = Field(default=10, ge=1)

class FederationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[FederationStatus] = None
    min_clients: Optional[int] = Field(default=None, ge=1)
    max_rounds: Optional[int] = Field(default=None, ge=1)

class FederationOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: FederationStatus
    min_clients: int
    max_rounds: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
