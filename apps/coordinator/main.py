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

    server = CoordinatorServer(
        host=args.host,
        port=args.port,
        min_clients=args.min_clients,
        num_rounds=args.num_rounds,
        round_timeout_seconds=args.round_timeout,
        heartbeat_timeout_seconds=args.heartbeat_timeout,
    )

    def _shutdown(signum, frame):  # noqa: ANN001
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

    done = server.state.wait_until_done(timeout=None)
    server.stop()
    logger.info("Training complete. %d rounds finished.", args.num_rounds)


if __name__ == "__main__":
    main()
