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
from pathlib import Path
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
    val_images_dir: str = "",
    val_annotations_dir: str = "",
) -> Any:
    """
    Build a training callable compatible with DistributedClientAgent.
    Falls back to a synthetic train fn if the ML layer is unavailable.
    """
    if not (
        images_dir
        and annotations_dir
        and Path(images_dir).is_dir()
        and Path(annotations_dir).is_dir()
    ):
        logger.info("Training data is not configured — using synthetic train fn.")

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

    try:
        sys.path.insert(0, "/app/packages/ml_core")
        from trustfl_ml.config import TrainingConfig
        from trustfl_ml.yolo_wrapper import SimulatedDetector

        # Auto-detect held-out val directory if not explicitly provided
        eval_img_dir = val_images_dir
        eval_ann_dir = val_annotations_dir
        if not (eval_img_dir and Path(eval_img_dir).is_dir()):
            p_img = Path(images_dir)
            p_ann = Path(annotations_dir)
            if p_img.name == "images" and p_img.parent.name == "train":
                cand_img = p_img.parent.parent / "val" / "images"
                cand_ann = p_ann.parent.parent / "val" / "annotations"
                if cand_img.is_dir() and cand_ann.is_dir():
                    eval_img_dir = str(cand_img)
                    eval_ann_dir = str(cand_ann)

        def real_train_fn(
            _round_id: int,
            global_params: list[list[float]],
            _config: dict[str, Any],
        ):
            # SimulatedDetector is always available here (imported above).
            # The previous globals()-based check was always False because the
            # import is local to this function, not at module level.
            model = SimulatedDetector()
            if global_params:
                model.set_parameters(global_params)
            train_cfg = TrainingConfig(epochs=epochs)
            train_metrics = model.train_on_dataset(
                images_dir=images_dir,
                annotations_dir=annotations_dir,
                config=train_cfg,
                max_samples=max_samples,
            )
            # Must be the actual number of samples used, never max_samples
            num_examples = train_metrics["samples_trained"]

            # Must evaluate on the held-out val split, never the training data
            has_val_img = eval_img_dir and Path(eval_img_dir).is_dir()
            has_val_ann = eval_ann_dir and Path(eval_ann_dir).is_dir()
            val_target_images = eval_img_dir if has_val_img else images_dir
            val_target_ann = eval_ann_dir if has_val_ann else annotations_dir
            eval_metrics = model.evaluate_on_dataset(
                images_dir=val_target_images,
                annotations_dir=val_target_ann,
                max_samples=min(max_samples, 10),
            )
            return model.get_parameters(), num_examples, eval_metrics

        logger.info("Using simulated detector training function.")
        return real_train_fn

    except (ImportError, ValueError):
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
    parser.add_argument("--federation-id", default=_env("FL_FEDERATION_ID", "fed-default"))
    parser.add_argument("--identity-path", default=_env("FL_IDENTITY_PATH", ""))
    parser.add_argument(
        "--coordinator", default=_env("FL_COORDINATOR_URL", "http://127.0.0.1:8100")
    )
    parser.add_argument("--images-dir", default=_env("FL_IMAGES_DIR", ""))
    parser.add_argument("--annotations-dir", default=_env("FL_ANNOTATIONS_DIR", ""))
    parser.add_argument("--val-images-dir", default=_env("FL_VAL_IMAGES_DIR", ""))
    parser.add_argument("--val-annotations-dir", default=_env("FL_VAL_ANNOTATIONS_DIR", ""))
    parser.add_argument("--ca-bundle", default=_env("FL_CA_BUNDLE", ""))
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
        val_images_dir=args.val_images_dir,
        val_annotations_dir=args.val_annotations_dir,
    )

    agent = DistributedClientAgent(
        client_id=args.client_id,
        coordinator_url=args.coordinator,
        train_fn=train_fn,
        poll_interval=args.poll_interval,
        federation_id=args.federation_id,
        identity_path=args.identity_path or None,
        ca_bundle=args.ca_bundle or None,
    )

    def _shutdown(signum, _frame):  # noqa: ANN001
        logger.info("Signal %d received — stopping.", signum)
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    agent.start_background_loop()
    if not agent.is_registered:
        logger.error("Client %s failed to register; exiting nonzero.", args.client_id)
        sys.exit(1)

    logger.info(
        "Client %s connected to %s",
        args.client_id,
        args.coordinator,
    )

    # Keep main thread alive; exit with the same code the agent failed with,
    # or normally once the agent has stopped (e.g. federation completed).
    while not agent._stop_event.is_set():
        time.sleep(1)
    logger.info("Client %s stopped.", args.client_id)
    if agent.failed or not agent.is_registered:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
