from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class BlockchainTxOut(BaseModel):
    id: str
    tx_hash: Optional[str]
    contract_name: str
    function_name: str
    status: str
    entity_id: Optional[str]
    entity_type: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    confirmed_at: Optional[datetime]
    model_config = {"from_attributes": True}
