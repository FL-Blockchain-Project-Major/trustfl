from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProofSubmit(BaseModel):
    id: str
    update_id: str
    client_id: str
    federation_id: str
    round_id: str
    model_version: str | None = None
    public_commitment: str
    protocol: str = "poseidon_commitment_v1"


class ProofOut(BaseModel):
    id: str
    update_id: str
    client_id: str
    federation_id: str
    round_id: str
    model_version: str | None
    public_commitment: str
    protocol: str
    is_valid: bool | None
    created_at: datetime
    model_config = {"from_attributes": True}
