from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ArtifactCreate(BaseModel):
    id: str
    federation_id: str
    round_number: Optional[int] = None
    client_id: Optional[str] = None
    uri: str
    sha256_hash: str
    size_bytes: Optional[int] = None
    model_version: Optional[str] = None

class ArtifactOut(BaseModel):
    id: str
    federation_id: str
    round_number: Optional[int]
    client_id: Optional[str]
    uri: str
    sha256_hash: str
    size_bytes: Optional[int]
    model_version: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}
