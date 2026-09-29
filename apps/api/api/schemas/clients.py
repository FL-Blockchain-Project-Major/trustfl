from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import json

class ClientRegister(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    federation_id: str
    public_key_b64: str
    capabilities: Optional[Dict[str, Any]] = None

class ClientOut(BaseModel):
    id: str
    federation_id: str
    public_key_b64: str
    is_active: bool
    capabilities: Optional[Dict[str, Any]] = None
    registered_at: datetime
    last_seen_at: Optional[datetime]
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_caps(cls, obj) -> "ClientOut":
        caps = None
        if obj.capabilities:
            try:
                caps = json.loads(obj.capabilities)
            except Exception:
                caps = None
        return cls(
            id=obj.id, federation_id=obj.federation_id,
            public_key_b64=obj.public_key_b64, is_active=obj.is_active,
            capabilities=caps, registered_at=obj.registered_at,
            last_seen_at=obj.last_seen_at
        )
