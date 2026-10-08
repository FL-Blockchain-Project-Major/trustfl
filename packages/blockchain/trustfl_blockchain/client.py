import json
import logging
import threading
import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from web3 import Web3
from web3.exceptions import ContractLogicError

logger = logging.getLogger(__name__)

class BlockchainClient:
    """
    Abstraction layer for TrustFL blockchain operations.
    Hides raw web3 calls and handles transaction retries, receipt parsing, etc.
    """

    def __init__(
        self,
        rpc_url: str,
        contracts_json_path: str,
        private_key: str,
        _network_name: str = "default",
        max_retries: int = 3,
        transaction_recorder: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to EVM at {rpc_url}")

        self.account = self.w3.eth.account.from_key(private_key)
        self.w3.eth.default_account = self.account.address
        self.max_retries = max_retries
        self.transaction_recorder = transaction_recorder
        # Serialise allocation, build/sign/send.  A receipt wait happens after
        # send, so independent transactions can still confirm concurrently.
        self._nonce_lock = threading.Lock()
        self._next_nonce: int | None = None
        self._pending_transactions: dict[str, dict[str, Any]] = {}

        with open(contracts_json_path) as f:
            data = json.load(f)

        contracts = data.get("contracts", {})

        self.client_registry = self.w3.eth.contract(
            address=contracts["ClientRegistry"]["address"],
            abi=contracts["ClientRegistry"]["abi"]
        )
        self.round_registry = self.w3.eth.contract(
            address=contracts["TrainingRoundRegistry"]["address"],
            abi=contracts["TrainingRoundRegistry"]["abi"]
        )
        self.update_registry = self.w3.eth.contract(
            address=contracts["UpdateRegistry"]["address"],
            abi=contracts["UpdateRegistry"]["abi"]
        )

    def _send_tx_with_retry(
        self, contract_func, error_context: str = "", *,
        contract_name: str, function_name: str,
        entity_id: str | None = None, entity_type: str | None = None,
    ) -> bool:
        """Helper to send a transaction with retry logic and receipt handling."""
        entity_key = f"{contract_name}:{function_name}:{entity_type}:{entity_id}"
        # Never re-broadcast an operation while a prior broadcast has an
        # unknown receipt.  Reconciliation determines its outcome first.
        if entity_key in self._pending_transactions:
            self.reconcile_pending()
            if entity_key in self._pending_transactions:
                logger.warning("%s has an unresolved prior broadcast", error_context)
                return False
        for attempt in range(self.max_retries):
            try:
                with self._nonce_lock:
                    if self._next_nonce is None:
                        self._next_nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
                    nonce = self._next_nonce
                    tx = contract_func.build_transaction({'from': self.account.address, "nonce": nonce})
                    signed_tx = self.account.sign_transaction(tx)
                    tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    self._next_nonce = nonce + 1
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

                if receipt.status == 1:
                    self._record_transaction(
                        contract_name, function_name, entity_id, entity_type,
                        tx_hash.hex(), "CONFIRMED", None,
                    )
                    logger.debug(f"{error_context} succeeded (tx: {tx_hash.hex()})")
                    return True
                else:
                    self._record_transaction(
                        contract_name, function_name, entity_id, entity_type,
                        tx_hash.hex(), "FAILED", "Transaction reverted on-chain",
                    )
                    logger.error(f"{error_context} failed on-chain (tx: {tx_hash.hex()})")
                    # If it failed on-chain (reverted), retrying exactly won't help unless state changes
                    return False

            except ContractLogicError as e:
                self._record_transaction(
                    contract_name, function_name, entity_id, entity_type,
                    None, "FAILED", str(e),
                )
                logger.error(f"{error_context} reverted: {e}")
                return False
            except Exception as e:
                logger.warning(f"{error_context} exception on attempt {attempt+1}: {e}")
                if "tx_hash" in locals():
                    self._pending_transactions[entity_key] = {
                        "tx_hash": tx_hash.hex(), "contract_name": contract_name,
                        "function_name": function_name, "entity_id": entity_id,
                        "entity_type": entity_type,
                    }
                    self._record_transaction(
                        contract_name, function_name, entity_id, entity_type,
                        tx_hash.hex(), "PENDING", f"Receipt unavailable: {e}",
                    )
                    logger.error("%s broadcast succeeded but confirmation is uncertain", error_context)
                    return False
                with self._nonce_lock:
                    self._next_nonce = None
                time.sleep(1)

        logger.error(f"{error_context} failed after {self.max_retries} attempts")
        self._record_transaction(
            contract_name, function_name, entity_id, entity_type,
            None, "FAILED", f"Failed after {self.max_retries} attempts",
        )
        return False

    def reconcile_pending(self) -> dict[str, str]:
        """Resolve uncertain broadcasts from receipt lookup without re-sending them.

        Returns a mapping of operation identity to CONFIRMED or FAILED.  Missing
        receipts deliberately remain pending; callers must not treat them as
        safe to retry with a new nonce.
        """
        resolved: dict[str, str] = {}
        for key, event in list(self._pending_transactions.items()):
            try:
                receipt = self.w3.eth.get_transaction_receipt(event["tx_hash"])
            except Exception:
                continue
            status = "CONFIRMED" if receipt.status == 1 else "FAILED"
            self._record_transaction(
                event["contract_name"], event["function_name"], event["entity_id"],
                event["entity_type"], event["tx_hash"], status,
                None if status == "CONFIRMED" else "Transaction reverted on-chain",
            )
            del self._pending_transactions[key]
            resolved[key] = status
        return resolved

    def _record_transaction(
        self, contract_name: str, function_name: str, entity_id: str | None,
        entity_type: str | None, tx_hash: str | None, status: str, error: str | None,
    ) -> None:
        if self.transaction_recorder:
            self.transaction_recorder({
                "id": sha256(
                    f"{contract_name}:{function_name}:{entity_type}:{entity_id}".encode()
                ).hexdigest(),
                "contract_name": contract_name, "function_name": function_name,
                "entity_id": entity_id, "entity_type": entity_type,
                "tx_hash": tx_hash, "status": status, "error": error,
            })

    def register_client(self, client_id: str, pubkey: str) -> bool:
        """Register a new client."""
        existing = self.client_registry.functions.getClient(client_id).call()
        if existing[1]:
            return True
        logger.info(f"Registering client {client_id} on-chain...")
        return self._send_tx_with_retry(
            self.client_registry.functions.registerClient(client_id, pubkey),
            f"register_client({client_id})", contract_name="ClientRegistry",
            function_name="registerClient", entity_id=client_id, entity_type="client",
        )

    def create_round(self, round_id: int, global_model_version: str) -> bool:
        """Create a new training round."""
        existing = self.round_registry.functions.getRound(round_id).call()
        if int(existing[2]) != 0:
            return True
        logger.info(f"Creating round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.createRound(round_id, global_model_version),
            f"create_round({round_id})", contract_name="TrainingRoundRegistry",
            function_name="createRound", entity_id=str(round_id), entity_type="round",
        )

    def activate_round(self, round_id: int) -> bool:
        """Activate a training round."""
        existing = self.round_registry.functions.getRound(round_id).call()
        status = int(existing[2])
        if status == 2:  # Active
            return True
        if status != 1:  # Created
            logger.error(
                "Cannot activate round %d with on-chain status %d",
                round_id,
                status,
            )
            return False
        logger.info(f"Activating round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.activateRound(round_id),
            f"activate_round({round_id})", contract_name="TrainingRoundRegistry",
            function_name="activateRound", entity_id=str(round_id), entity_type="round",
        )

    def finalize_round(self, round_id: int, new_global_model_version: str) -> bool:
        """Finalize a training round with new global model hash."""
        existing = self.round_registry.functions.getRound(round_id).call()
        status = int(existing[2])
        if status == 3:
            return existing[1] == new_global_model_version
        if status != 2:
            logger.error("Cannot finalize round %d with on-chain status %d", round_id, status)
            return False
        logger.info(f"Finalizing round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.finalizeRound(round_id, new_global_model_version),
            f"finalize_round({round_id})", contract_name="TrainingRoundRegistry",
            function_name="finalizeRound", entity_id=str(round_id), entity_type="round",
        )

    def submit_update(self, update_id: str, round_id: int, client_id: str, artifact_hash: str, nonce: str) -> bool:
        """Submit a signed update metadata to the registry."""
        existing = self.update_registry.functions.getUpdate(update_id).call()
        if existing[4] != 0:
            return True
        logger.info(f"Submitting update {update_id} from {client_id} for round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.update_registry.functions.submitUpdate(update_id, round_id, client_id, artifact_hash, nonce),
            f"submit_update({update_id})", contract_name="UpdateRegistry",
            function_name="submitUpdate", entity_id=update_id, entity_type="update",
        )

    def mark_verification_state(self, update_id: str, is_valid: bool, reason_code: str | None = None) -> bool:
        """Mark an update as verified or rejected."""
        existing = self.update_registry.functions.getUpdate(update_id).call()
        if existing[4] in (2, 4):
            return existing[4] == 2 if is_valid else existing[4] == 4
        state_str = "Verified" if is_valid else "Rejected"
        logger.info(f"Marking update {update_id} as {state_str} on-chain...")
        operation = (
            self.update_registry.functions.markRejected(update_id, reason_code or "UNSPECIFIED")
            if not is_valid and reason_code else
            self.update_registry.functions.markVerificationState(update_id, is_valid)
        )
        return self._send_tx_with_retry(
            operation,
            f"mark_verification_state({update_id})", contract_name="UpdateRegistry",
            function_name="markVerificationState", entity_id=update_id, entity_type="update",
        )

    def record_aggregation(self, update_id: str) -> bool:
        """Record that an update was included in the final aggregation."""
        existing = self.update_registry.functions.getUpdate(update_id).call()
        if existing[4] == 3:
            return True
        logger.info(f"Recording aggregation for update {update_id} on-chain...")
        return self._send_tx_with_retry(
            self.update_registry.functions.recordAggregation(update_id),
            f"record_aggregation({update_id})", contract_name="UpdateRegistry",
            function_name="recordAggregation", entity_id=update_id, entity_type="update",
        )
