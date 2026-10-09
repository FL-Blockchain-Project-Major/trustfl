from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.api.api.db.models import FederationStatus


class FederationCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    min_clients: int = Field(default=2, ge=1)
    max_rounds: int = Field(default=10, ge=1)


class FederationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: FederationStatus | None = None
    min_clients: int | None = Field(default=None, ge=1)
    max_rounds: int | None = Field(default=None, ge=1)


class FederationOut(BaseModel):
    id: str
    name: str
    description: str | None
    status: FederationStatus
    min_clients: int
    max_rounds: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
