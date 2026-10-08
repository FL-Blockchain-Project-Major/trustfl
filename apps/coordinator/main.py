"""
Coordinator entry point (Docker / CLI).

Usage:
    python main.py [--host HOST] [--port PORT] [--min-clients N]
                   [--num-rounds N] [--round-timeout SECS]
                   [--heartbeat-timeout SECS]

Environment variables (override CLI):
    COORDINATOR_HOST, COORDINATOR_PORT, FL_MIN_CLIENTS,
    FL_NUM_ROUNDS, FL_ROUND_TIMEOUT_SECONDS, FL_HEARTBEAT_TIMEOUT_SECONDS
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("coordinator.main")


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float_env(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustFL Coordinator")
    parser.add_argument("--host", default=os.environ.get("COORDINATOR_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=_int_env("COORDINATOR_PORT", 8100))
    parser.add_argument("--min-clients", type=int, default=_int_env("FL_MIN_CLIENTS", 2))
    parser.add_argument("--num-rounds", type=int, default=_int_env("FL_NUM_ROUNDS", 3))
    parser.add_argument(
        "--round-timeout",
        type=float,
        default=_float_env("FL_ROUND_TIMEOUT_SECONDS", 60.0),
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=_float_env("FL_HEARTBEAT_TIMEOUT_SECONDS", 30.0),
    )
    args = parser.parse_args()

    # Import here so the module is importable without network deps
    from network.server import CoordinatorServer

    blockchain_client = None
    transaction_recorder = None
    if os.getenv("BLOCKCHAIN_ENABLED", "false").lower() == "true":
        from packages.blockchain.trustfl_blockchain.client import BlockchainClient

        def transaction_recorder(event):
            try:
                from apps.api.api.db.session import SessionLocal
                from apps.api.api.services.blockchain_service import BlockchainTxService

                with SessionLocal() as db:
                    service = BlockchainTxService(db)
                    service.record(
                        id=event["id"],
                        contract_name=event["contract_name"],
                        function_name=event["function_name"],
                        entity_id=event["entity_id"],
                        entity_type=event["entity_type"],
                        tx_hash=event["tx_hash"],
                        status=event["status"],
                        error=event["error"],
                    )
            except Exception:
                logger.exception("Unable to persist blockchain transaction audit event")

        blockchain_client = BlockchainClient(
            rpc_url=os.environ["BLOCKCHAIN_RPC_URL"],
            contracts_json_path=os.environ["BLOCKCHAIN_CONTRACTS_JSON"],
            private_key=os.environ["COORDINATOR_PRIVATE_KEY"],
            transaction_recorder=transaction_recorder,
        )

    from packages.storage.trustfl_storage.client import IPFSStorageClient, LocalStorageClient
    storage_client = (
        IPFSStorageClient(os.environ["IPFS_API_URL"])
        if os.getenv("STORAGE_BACKEND", "local").lower() == "ipfs"
        else LocalStorageClient(os.getenv("STORAGE_LOCAL_DIR", "/tmp/trustfl-artifacts"))
    )
    from apps.coordinator.persistence import CoordinatorPersistence
    persistence = CoordinatorPersistence()
    persistence.ensure_federation(args.min_clients, args.num_rounds)

    server = CoordinatorServer(
        host=args.host,
        port=args.port,
        min_clients=args.min_clients,
        num_rounds=args.num_rounds,
        round_timeout_seconds=args.round_timeout,
        heartbeat_timeout_seconds=args.heartbeat_timeout,
        require_signatures=os.getenv(
            "COORDINATOR_REQUIRE_SIGNATURES",
            "true" if os.getenv("ENVIRONMENT", "production").lower() == "production" else "false",
        ).lower() == "true",
        blockchain_client=blockchain_client,
        storage_client=storage_client,
        persistence=persistence,
    )

    def _shutdown(signum, _frame):  # noqa: ANN001
        logger.info("Signal %d received — stopping.", signum)
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.start()
    logger.info(
        "Coordinator running: %s:%d  min_clients=%d  num_rounds=%d",
        args.host, args.port, args.min_clients, args.num_rounds,
    )

    server.state.wait_until_done(timeout=None)
    server.stop()
    logger.info("Training complete. %d rounds finished.", args.num_rounds)


if __name__ == "__main__":
    main()
