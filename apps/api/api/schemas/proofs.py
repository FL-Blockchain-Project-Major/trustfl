from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ProofSubmit(BaseModel):
    id: str
    update_id: str
    client_id: str
    federation_id: str
    round_id: str
    model_version: Optional[str] = None
    public_commitment: str
    protocol: str = "poseidon_commitment_v1"

class ProofOut(BaseModel):
    id: str
    update_id: str
    client_id: str
    federation_id: str
    round_id: str
    model_version: Optional[str]
    public_commitment: str
    protocol: str
    is_valid: Optional[bool]
    created_at: datetime
    model_config = {"from_attributes": True}
