from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ClientRegister(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    federation_id: str
    public_key_b64: str
    capabilities: dict[str, Any] | None = None


class ClientOut(BaseModel):
    id: str
    federation_id: str
    public_key_b64: str
    is_active: bool
    capabilities: dict[str, Any] | None = None
    registered_at: datetime
    last_seen_at: datetime | None
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_caps(cls, obj) -> ClientOut:
        caps = None
        if obj.capabilities:
            try:
                caps = json.loads(obj.capabilities)
            except Exception:
                caps = None
        return cls(
            id=obj.id,
            federation_id=obj.federation_id,
            public_key_b64=obj.public_key_b64,
            is_active=obj.is_active,
            capabilities=caps,
            registered_at=obj.registered_at,
            last_seen_at=obj.last_seen_at,
        )
