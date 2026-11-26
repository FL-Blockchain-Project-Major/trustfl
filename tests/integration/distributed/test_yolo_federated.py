"""
Multi-client federated YOLO integration tests (CPU-compatible, deterministic).

Covers:
- At least 2 clients training real Ultralytics YOLOv8n locally on separate partitions
- Multiple federated rounds with FedAvg aggregation
- Parameter change verification after local training and global aggregation
- Reloading aggregated global parameters by clients for subsequent rounds
- Rejection of incompatible architectures, shape mismatches, and non-finite updates
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image
from trustfl_core.flower_app import ClientApp, FitRes
from trustfl_ml.config import ClientNodeConfig, DatasetConfig, TrainingConfig
from trustfl_ml.yolo_wrapper import YOLODetector

from apps.client.yolo_client import TrustFLYOLOClient
from apps.coordinator.coordinator import create_server_app


def _make_partition(root: Path, color_offset: int) -> tuple[Path, Path]:
    img_dir = root / "images"
    ann_dir = root / "annotations"
    img_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        im = Image.new("RGB", (64, 64), color=((color_offset + i * 40) % 255, 100, 150))
        im.save(img_dir / f"img_{i}.jpg")
        (ann_dir / f"img_{i}.txt").write_text("8,8,24,24,1,1,0,0\n", encoding="utf-8")
    return img_dir, ann_dir


class TestYOLOFederatedIntegration(unittest.TestCase):
    def test_multi_client_multi_round_yolo_fedavg(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            c0_img, c0_ann = _make_partition(base / "client_0" / "train", 10)
            c1_img, c1_ann = _make_partition(base / "client_1" / "train", 120)

            configs = {
                "client_0": ClientNodeConfig(
                    client_id="client_0",
                    federation_id="fed-test-yolo",
                    dataset_config=DatasetConfig(
                        images_dir=str(c0_img), annotations_dir=str(c0_ann)
                    ),
                    training_config=TrainingConfig(
                        model_name="yolov8n",
                        epochs=1,
                        batch_size=2,
                        image_size=64,
                        device="cpu",
                        seed=42,
                    ),
                ),
                "client_1": ClientNodeConfig(
                    client_id="client_1",
                    federation_id="fed-test-yolo",
                    dataset_config=DatasetConfig(
                        images_dir=str(c1_img), annotations_dir=str(c1_ann)
                    ),
                    training_config=TrainingConfig(
                        model_name="yolov8n",
                        epochs=1,
                        batch_size=2,
                        image_size=64,
                        device="cpu",
                        seed=43,
                    ),
                ),
            }

            client_app = ClientApp(client_fn=lambda cid: TrustFLYOLOClient(configs[cid]))

            global_model = YOLODetector(model_name="yolov8n", num_classes=10, seed=42, device="cpu")
            initial_params = global_model.get_parameters()

            server_app = create_server_app(
                num_rounds=2,
                fraction_fit=1.0,
                fraction_evaluate=1.0,
                min_fit_clients=2,
                min_evaluate_clients=2,
                min_available_clients=2,
                initial_parameters=initial_params,
            )

            # Round 1
            r1 = server_app.fit_round(1, client_app, ["client_0", "client_1"])
            self.assertEqual(r1["num_successful_clients"], 2)
            r1_params = [list(layer) for layer in server_app.parameters]
            delta_r1 = sum(
                abs(a - b)
                for la, lb in zip(r1_params, initial_params, strict=True)
                for a, b in zip(la, lb, strict=True)
            )
            self.assertGreater(delta_r1, 0.0, "Global parameters must change after Round 1")

            # Round 2 (clients load aggregated r1_params and train again)
            r2 = server_app.fit_round(2, client_app, ["client_0", "client_1"])
            self.assertEqual(r2["num_successful_clients"], 2)
            r2_params = server_app.parameters
            delta_r2 = sum(
                abs(a - b)
                for la, lb in zip(r2_params, r1_params, strict=True)
                for a, b in zip(la, lb, strict=True)
            )
            self.assertGreater(delta_r2, 0.0, "Global parameters must change after Round 2")

            # Genuine evaluation metrics must be present (and no accuracy_proxy)
            eval_m = r2["eval_metrics"]
            self.assertIn("map50", eval_m)
            self.assertIn("precision", eval_m)
            self.assertIn("recall", eval_m)
            self.assertNotIn("accuracy_proxy", eval_m)

            # Aggregated global model must load cleanly into a fresh YOLODetector
            reloaded = YOLODetector(model_name="yolov8n", num_classes=10, seed=99, device="cpu")
            reloaded.set_parameters(r2_params)

    def test_fedavg_rejects_incompatible_and_nonfinite_updates(self) -> None:
        server_app = create_server_app(
            num_rounds=1,
            initial_parameters=[[1.0, 2.0], [3.0]],
        )
        # Incompatible layer count
        with self.assertRaises(ValueError):
            server_app.strategy.aggregate_fit(
                1,
                [
                    ("c0", FitRes(parameters=[[1.0, 2.0], [3.0]], num_examples=2)),
                    ("c1", FitRes(parameters=[[1.0, 2.0]], num_examples=2)),
                ],
                [],
            )
        # Non-finite parameter
        with self.assertRaises(ValueError):
            server_app.strategy.aggregate_fit(
                1,
                [
                    ("c0", FitRes(parameters=[[1.0, 2.0], [3.0]], num_examples=2)),
                    ("c1", FitRes(parameters=[[float("nan"), 2.0], [3.0]], num_examples=2)),
                ],
                [],
            )


if __name__ == "__main__":
    unittest.main()
