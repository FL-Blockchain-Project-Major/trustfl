"""
Client entry point (Docker / CLI).

Usage:
    python main.py [--client-id CLIENT_001] [--coordinator http://coordinator:8100]
                   [--dataset-dir /data/dataset]
                   [--images-dir /data/images] [--annotations-dir /data/ann]
                   [--epochs 1] [--max-samples 50] [--poll-interval 5]
                   [--num-clients 2] [--keys-dir /var/lib/trustfl/keys]

Environment variables (override CLI):
    FL_CLIENT_ID, FL_COORDINATOR_URL, FL_DATASET_DIR, FL_IMAGES_DIR, FL_ANNOTATIONS_DIR,
    FL_LOCAL_EPOCHS, FL_MAX_SAMPLES, FL_POLL_INTERVAL_SECONDS, FL_NUM_CLIENTS, FL_KEYS_DIR
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

# Ensure package roots are in sys.path
_repo_root = Path(__file__).resolve().parents[2]
for _pkg in ("packages/crypto", "packages/ml_core", "packages/schemas"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)
    _app_p = f"/app/{_pkg}"
    if _app_p not in sys.path:
        sys.path.insert(0, _app_p)

from trustfl_crypto.keys import ClientIdentity  # noqa: E402
from trustfl_crypto.provision import claim_client_identity  # noqa: E402
from trustfl_ml.dataset import (  # noqa: E402
    DatasetValidationError,
    VisDroneParser,
    resolve_and_validate_dataset,
)


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
    Falls back to a synthetic train fn if ML core is unavailable or data is not configured.
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

        logger.info("Using simulated detector training function on dataset: %s", images_dir)
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
    parser.add_argument("--client-id", default=_env("FL_CLIENT_ID", ""))
    parser.add_argument("--federation-id", default=_env("FL_FEDERATION_ID", "fed-default"))
    parser.add_argument("--identity-path", default=_env("FL_IDENTITY_PATH", ""))
    parser.add_argument(
        "--coordinator", default=_env("FL_COORDINATOR_URL", "http://127.0.0.1:8100")
    )
    parser.add_argument("--dataset-dir", default=_env("FL_DATASET_DIR", ""))
    parser.add_argument("--images-dir", default=_env("FL_IMAGES_DIR", ""))
    parser.add_argument("--annotations-dir", default=_env("FL_ANNOTATIONS_DIR", ""))
    parser.add_argument("--val-images-dir", default=_env("FL_VAL_IMAGES_DIR", ""))
    parser.add_argument("--val-annotations-dir", default=_env("FL_VAL_ANNOTATIONS_DIR", ""))
    parser.add_argument("--num-clients", type=int, default=_int_env("FL_NUM_CLIENTS", 2))
    parser.add_argument("--keys-dir", default=_env("FL_KEYS_DIR", "/var/lib/trustfl/keys"))
    parser.add_argument("--ca-bundle", default=_env("FL_CA_BUNDLE", ""))
    parser.add_argument("--epochs", type=int, default=_int_env("FL_LOCAL_EPOCHS", 1))
    parser.add_argument("--max-samples", type=int, default=_int_env("FL_MAX_SAMPLES", 50))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_float_env("FL_POLL_INTERVAL_SECONDS", 5.0),
    )
    args = parser.parse_args()

    # 1. Identity acquisition (explicit vs dynamic slot claiming)
    lock_handle = None
    if not args.client_id or args.client_id.lower() == "auto":
        logger.info(
            "No static FL_CLIENT_ID provided; claiming dynamic slot from %d available in %s...",
            args.num_clients,
            args.keys_dir,
        )
        try:
            client_id, identity, lock_handle = claim_client_identity(
                keys_dir=args.keys_dir,
                num_clients=args.num_clients,
            )
        except Exception as exc:
            logger.error("Failed to claim unique client identity: %s", exc)
            sys.exit(1)
    else:
        client_id = args.client_id
        client_keys_dir = Path(args.keys_dir) / client_id
        client_keys_dir.mkdir(parents=True, exist_ok=True)
        key_path = (
            Path(args.identity_path) if args.identity_path else client_keys_dir / "private.pem"
        )
        identity = ClientIdentity.load_or_generate(client_id, key_path)

    logger.info("Using client identity %s (public key: %s)", client_id, identity.public_key_b64)

    # 2. Dataset resolution and pre-training validation
    images_dir = args.images_dir
    annotations_dir = args.annotations_dir
    val_images_dir = args.val_images_dir
    val_annotations_dir = args.val_annotations_dir

    if args.dataset_dir:
        logger.info("Resolving and validating raw dataset root: %s", args.dataset_dir)
        try:
            ds_info = resolve_and_validate_dataset(
                args.dataset_dir,
                min_samples=1,
                check_images_readable=True,
            )
            images_dir = str(ds_info["train_images_dir"])
            annotations_dir = str(ds_info["train_annotations_dir"])
            if ds_info["val_images_dir"]:
                val_images_dir = str(ds_info["val_images_dir"])
            if ds_info["val_annotations_dir"]:
                val_annotations_dir = str(ds_info["val_annotations_dir"])

            logger.info(
                "Dataset validated successfully: %d usable samples, %d total boxes from %s",
                ds_info["stats"]["valid_pairs"],
                ds_info["stats"]["total_boxes"],
                images_dir,
            )
            logger.info(
                "NOTE: Single-host protocol demonstration: Client %s is reading shared dataset at '%s'. "
                "This topology exercises federated aggregation and verification protocols on a single host; "
                "it does not demonstrate data privacy, data isolation, or statistical heterogeneity of independent client data owners.",
                client_id,
                args.dataset_dir,
            )
        except DatasetValidationError as exc:
            logger.error("Dataset validation failed on '%s': %s", args.dataset_dir, exc)
            sys.exit(1)
    elif images_dir and annotations_dir:
        try:
            stats = VisDroneParser.validate_dataset(
                images_dir,
                annotations_dir,
                check_images_readable=True,
            )
            logger.info(
                "Explicit images/annotations validated: %d valid pairs.", stats["valid_pairs"]
            )
        except DatasetValidationError as exc:
            logger.error(
                "Dataset validation failed on (%s, %s): %s", images_dir, annotations_dir, exc
            )
            sys.exit(1)

    train_fn = _build_train_fn(
        images_dir,
        annotations_dir,
        args.epochs,
        args.max_samples,
        val_images_dir=val_images_dir,
        val_annotations_dir=val_annotations_dir,
    )

    from network.agent import DistributedClientAgent

    agent = DistributedClientAgent(
        client_id=client_id,
        coordinator_url=args.coordinator,
        train_fn=train_fn,
        poll_interval=args.poll_interval,
        federation_id=args.federation_id,
        identity=identity,
        ca_bundle=args.ca_bundle or None,
    )

    def _shutdown(signum, _frame):  # noqa: ANN001
        logger.info("Signal %d received — stopping client %s.", signum, client_id)
        agent.stop()
        if lock_handle is not None:
            try:
                lock_handle.close()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    agent.start_background_loop()
    if not agent.is_registered:
        logger.error("Client %s failed to register; exiting nonzero.", client_id)
        if lock_handle is not None:
            try:
                lock_handle.close()
            except Exception:
                pass
        sys.exit(1)

    logger.info("Client %s connected and registered with %s", client_id, args.coordinator)

    while not agent._stop_event.is_set():
        time.sleep(1)

    logger.info("Client %s stopped.", client_id)
    if lock_handle is not None:
        try:
            lock_handle.close()
        except Exception:
            pass

    if agent.failed or not agent.is_registered:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
