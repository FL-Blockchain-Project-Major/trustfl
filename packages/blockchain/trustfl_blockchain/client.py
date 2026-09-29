import json
import logging
import time
from typing import Dict, Any, Optional

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
        network_name: str = "default",
        max_retries: int = 3,
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to EVM at {rpc_url}")

        self.account = self.w3.eth.account.from_key(private_key)
        self.w3.eth.default_account = self.account.address
        self.max_retries = max_retries

        with open(contracts_json_path, "r") as f:
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

    def _send_tx_with_retry(self, contract_func, error_context: str = "") -> bool:
        """Helper to send a transaction with retry logic and receipt handling."""
        for attempt in range(self.max_retries):
            try:
                # We fetch the current nonce per attempt in case of stuck transactions
                nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
                
                # Build transaction
                tx = contract_func.build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                })
                
                signed_tx = self.account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                
                if receipt.status == 1:
                    logger.debug(f"{error_context} succeeded (tx: {tx_hash.hex()})")
                    return True
                else:
                    logger.error(f"{error_context} failed on-chain (tx: {tx_hash.hex()})")
                    # If it failed on-chain (reverted), retrying exactly won't help unless state changes
                    return False

            except ContractLogicError as e:
                logger.error(f"{error_context} reverted: {e}")
                return False
            except Exception as e:
                logger.warning(f"{error_context} exception on attempt {attempt+1}: {e}")
                time.sleep(1)
                
        logger.error(f"{error_context} failed after {self.max_retries} attempts")
        return False

    def register_client(self, client_id: str, pubkey: str) -> bool:
        """Register a new client."""
        logger.info(f"Registering client {client_id} on-chain...")
        return self._send_tx_with_retry(
            self.client_registry.functions.registerClient(client_id, pubkey),
            f"register_client({client_id})"
        )

    def create_round(self, round_id: int, global_model_version: str) -> bool:
        """Create a new training round."""
        logger.info(f"Creating round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.createRound(round_id, global_model_version),
            f"create_round({round_id})"
        )

    def activate_round(self, round_id: int) -> bool:
        """Activate a training round."""
        logger.info(f"Activating round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.activateRound(round_id),
            f"activate_round({round_id})"
        )

    def finalize_round(self, round_id: int, new_global_model_version: str) -> bool:
        """Finalize a training round with new global model hash."""
        logger.info(f"Finalizing round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.round_registry.functions.finalizeRound(round_id, new_global_model_version),
            f"finalize_round({round_id})"
        )

    def submit_update(self, update_id: str, round_id: int, client_id: str, artifact_hash: str, nonce: str) -> bool:
        """Submit a signed update metadata to the registry."""
        logger.info(f"Submitting update {update_id} from {client_id} for round {round_id} on-chain...")
        return self._send_tx_with_retry(
            self.update_registry.functions.submitUpdate(update_id, round_id, client_id, artifact_hash, nonce),
            f"submit_update({update_id})"
        )

    def mark_verification_state(self, update_id: str, is_valid: bool) -> bool:
        """Mark an update as verified or rejected."""
        state_str = "Verified" if is_valid else "Rejected"
        logger.info(f"Marking update {update_id} as {state_str} on-chain...")
        return self._send_tx_with_retry(
            self.update_registry.functions.markVerificationState(update_id, is_valid),
            f"mark_verification_state({update_id})"
        )

    def record_aggregation(self, update_id: str) -> bool:
        """Record that an update was included in the final aggregation."""
        logger.info(f"Recording aggregation for update {update_id} on-chain...")
        return self._send_tx_with_retry(
            self.update_registry.functions.recordAggregation(update_id),
            f"record_aggregation({update_id})"
        )
