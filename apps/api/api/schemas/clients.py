from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from apps.api.api.db.models import ClientLifecycleStatus


class ClientRegister(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    federation_id: str
    public_key_b64: str
    capabilities: dict[str, Any] | None = None


class ClientLifecycleUpdate(BaseModel):
    status: ClientLifecycleStatus
    key_expires_at: datetime | None = None


class ClientKeyRotation(BaseModel):
    public_key_b64: str = Field(..., min_length=32)


class ClientOut(BaseModel):
    id: str
    federation_id: str
    public_key_b64: str
    is_active: bool
    lifecycle_status: ClientLifecycleStatus
    key_version: int
    key_expires_at: datetime | None
    enrolled_at: datetime | None
    revoked_at: datetime | None
    suspended_at: datetime | None
    enrollment_id: str | None
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
            lifecycle_status=obj.lifecycle_status,
            key_version=obj.key_version,
            key_expires_at=obj.key_expires_at,
            enrolled_at=obj.enrolled_at,
            revoked_at=obj.revoked_at,
            suspended_at=obj.suspended_at,
            enrollment_id=obj.enrollment_id,
            capabilities=caps,
            registered_at=obj.registered_at,
            last_seen_at=obj.last_seen_at,
        )
