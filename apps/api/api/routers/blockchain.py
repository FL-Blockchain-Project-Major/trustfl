from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.api.db.session import get_db
from apps.api.api.schemas.blockchain import BlockchainTxOut
from apps.api.api.schemas.common import APIResponse
from apps.api.api.services.blockchain_service import BlockchainTxService

router = APIRouter(prefix="/blockchain", tags=["Blockchain"])


class TxCreate(BaseModel):
    id: str
    contract_name: str
    function_name: str
    entity_id: str = None
    entity_type: str = None
    tx_hash: str = None
    status: str = "PENDING"


class TxConfirm(BaseModel):
    tx_hash: str


class TxFail(BaseModel):
    error: str


def get_service(db: Session = Depends(get_db)) -> BlockchainTxService:  # noqa: B008
    return BlockchainTxService(db)


@router.get("/transactions", response_model=APIResponse[list[BlockchainTxOut]])
def list_transactions(
    skip: int = 0,
    limit: int = 100,
    service: BlockchainTxService = Depends(get_service),  # noqa: B008
):  # noqa: B008
    return APIResponse(data=service.list_all(skip=skip, limit=min(limit, 100)))


@router.post("/transactions", response_model=APIResponse[BlockchainTxOut])
def record_tx(payload: TxCreate, service: BlockchainTxService = Depends(get_service)):  # noqa: B008
    tx = service.record(
        id=payload.id,
        contract_name=payload.contract_name,
        function_name=payload.function_name,
        entity_id=payload.entity_id,
        entity_type=payload.entity_type,
        tx_hash=payload.tx_hash,
        status=payload.status,
    )
    return APIResponse(data=tx)


@router.put("/transactions/{tx_id}/confirm", response_model=APIResponse[BlockchainTxOut])
def confirm_tx(tx_id: str, payload: TxConfirm, service: BlockchainTxService = Depends(get_service)):  # noqa: B008
    tx = service.confirm(tx_id, payload.tx_hash)
    return APIResponse(data=tx)


@router.put("/transactions/{tx_id}/fail", response_model=APIResponse[BlockchainTxOut])
def fail_tx(tx_id: str, payload: TxFail, service: BlockchainTxService = Depends(get_service)):  # noqa: B008
    tx = service.fail(tx_id, payload.error)
    return APIResponse(data=tx)
