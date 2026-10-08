from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ArtifactCreate(BaseModel):
    id: str
    federation_id: str
    round_number: int | None = None
    client_id: str | None = None
    uri: str
    sha256_hash: str
    size_bytes: int | None = None
    model_version: str | None = None

class ArtifactOut(BaseModel):
    id: str
    federation_id: str
    round_number: int | None
    client_id: str | None
    uri: str
    sha256_hash: str
    size_bytes: int | None
    model_version: str | None
    created_at: datetime
    model_config = {"from_attributes": True}
