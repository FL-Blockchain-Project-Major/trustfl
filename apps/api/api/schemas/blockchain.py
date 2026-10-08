from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BlockchainTxOut(BaseModel):
    id: str
    tx_hash: str | None
    contract_name: str
    function_name: str
    status: str
    entity_id: str | None
    entity_type: str | None
    error_message: str | None
    created_at: datetime
    confirmed_at: datetime | None
    model_config = {"from_attributes": True}
