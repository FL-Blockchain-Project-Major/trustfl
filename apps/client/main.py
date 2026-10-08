"""
Client entry point (Docker / CLI).

Usage:
    python main.py --client-id CLIENT_001 --coordinator http://coordinator:8100
                   [--images-dir /data/images] [--annotations-dir /data/ann]
                   [--epochs 1] [--max-samples 50] [--poll-interval 5]

Environment variables (override CLI):
    FL_CLIENT_ID, FL_COORDINATOR_URL, FL_IMAGES_DIR, FL_ANNOTATIONS_DIR,
    FL_LOCAL_EPOCHS, FL_MAX_SAMPLES, FL_POLL_INTERVAL_SECONDS
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("client.main")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float_env(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _build_train_fn(
    images_dir: str,
    annotations_dir: str,
    epochs: int,
    max_samples: int,
) -> Any:
    """
    Build a training callable compatible with DistributedClientAgent.
    Falls back to a synthetic train fn if the ML layer is unavailable.
    """
    try:
        sys.path.insert(0, "/app/packages/ml_core")
        from trustfl_ml.config import TrainingConfig
        from trustfl_ml.yolo_wrapper import YOLOModelWrapper

        def real_train_fn(
            _round_id: int,
            global_params: list[list[float]],
            _config: dict[str, Any],
        ):
            model = YOLOModelWrapper()
            if global_params:
                model.set_parameters(global_params)
            train_cfg = TrainingConfig(local_epochs=epochs)
            model.train_on_dataset(
                images_dir=images_dir,
                annotations_dir=annotations_dir,
                config=train_cfg,
                max_samples=max_samples,
            )
            eval_metrics = model.evaluate_on_dataset(
                images_dir=images_dir,
                annotations_dir=annotations_dir,
                max_samples=min(max_samples, 10),
            )
            num_examples = max_samples
            return model.get_parameters(), num_examples, eval_metrics

        logger.info("Using real YOLO training function.")
        return real_train_fn

    except ImportError:
        logger.warning("ML core not available — using synthetic train fn.")

        def synthetic_train_fn(
            _round_id: int,
            global_params: list[list[float]],
            _config: dict[str, Any],
        ):
            import random
            params = global_params if global_params else [[random.gauss(0, 0.1) for _ in range(10)]]
            updated = [[v + random.gauss(0, 0.01) for v in layer] for layer in params]
            return updated, 50, {"loss": random.uniform(0.3, 0.7)}

        return synthetic_train_fn


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustFL Client")
    parser.add_argument("--client-id", default=_env("FL_CLIENT_ID", "client_001"))
    parser.add_argument(
        "--coordinator", default=_env("FL_COORDINATOR_URL", "http://127.0.0.1:8100")
    )
    parser.add_argument("--images-dir", default=_env("FL_IMAGES_DIR", ""))
    parser.add_argument("--annotations-dir", default=_env("FL_ANNOTATIONS_DIR", ""))
    parser.add_argument("--epochs", type=int, default=_int_env("FL_LOCAL_EPOCHS", 1))
    parser.add_argument("--max-samples", type=int, default=_int_env("FL_MAX_SAMPLES", 50))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_float_env("FL_POLL_INTERVAL_SECONDS", 5.0),
    )
    args = parser.parse_args()

    from network.agent import DistributedClientAgent

    train_fn = _build_train_fn(
        args.images_dir,
        args.annotations_dir,
        args.epochs,
        args.max_samples,
    )

    agent = DistributedClientAgent(
        client_id=args.client_id,
        coordinator_url=args.coordinator,
        train_fn=train_fn,
        poll_interval=args.poll_interval,
    )

    def _shutdown(signum, _frame):  # noqa: ANN001
        logger.info("Signal %d received — stopping.", signum)
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    agent.start_background_loop()
    logger.info(
        "Client %s connected to %s",
        args.client_id, args.coordinator,
    )

    # Keep main thread alive
    while not agent._stop_event.is_set():
        time.sleep(1)


if __name__ == "__main__":
    main()
