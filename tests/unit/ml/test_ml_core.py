"""
Unit tests for real Ultralytics YOLO, VisDrone dataset validation, training config,
and checkpoint management.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image as PILImage
from trustfl_ml.checkpoint import ParameterSerialization
from trustfl_ml.config import DatasetConfig, TrainingConfig
from trustfl_ml.dataset import DatasetValidationError, VisDroneParser
from trustfl_ml.yolo_wrapper import YOLODetector, YOLOModelWrapper, verify_weights_checksum


def _create_tiny_visdrone_dataset(root: Path, num_images: int = 4) -> tuple[Path, Path]:
    img_dir = root / "images"
    ann_dir = root / "annotations"
    img_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)
    for i in range(num_images):
        img = PILImage.new("RGB", (64, 64), color=((i * 50) % 255, 80, 120))
        img.save(img_dir / f"img{i:03d}.jpg")
        # VisDrone CSV: left,top,width,height,score,category,truncation,occlusion
        (ann_dir / f"img{i:03d}.txt").write_text(
            "10,10,20,20,1,1,0,0\n30,25,18,18,1,4,0,0\n",
            encoding="utf-8",
        )
    return img_dir, ann_dir


class TestMLCore(unittest.TestCase):
    def test_model_initialization(self) -> None:
        model = YOLOModelWrapper(model_name="yolov8n", num_classes=10, seed=42, device="cpu")
        params = model.get_parameters()
        self.assertGreater(len(params), 100)
        self.assertGreater(model.parameter_count(), 1_000_000)

    def test_parameter_round_trips_and_checksum(self) -> None:
        small_params = [[0.1, -0.2, 0.3], [1.0, 2.0]]
        data_bytes = ParameterSerialization.parameters_to_bytes(small_params)
        restored = ParameterSerialization.bytes_to_parameters(data_bytes)
        self.assertEqual(len(small_params), len(restored))
        for l1, l2 in zip(small_params, restored, strict=True):
            for v1, v2 in zip(l1, l2, strict=True):
                self.assertAlmostEqual(v1, v2, places=6)

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            saved_path, sha = ParameterSerialization.save_checkpoint(
                small_params, ckpt_path, metadata={"epoch": 1, "map50": 0.45}
            )
            self.assertTrue(saved_path.is_file())
            self.assertEqual(len(sha), 64)

            loaded_params, meta = ParameterSerialization.load_checkpoint(ckpt_path)
            self.assertEqual(meta["epoch"], 1)
            self.assertEqual(meta["map50"], 0.45)
            self.assertEqual(len(loaded_params), len(small_params))

            # Tampered checkpoint must fail SHA-256 verification
            tampered = ckpt_path.read_text(encoding="utf-8").replace("0.3", "0.9")
            ckpt_path.write_text(tampered, encoding="utf-8")
            with self.assertRaises(ValueError):
                ParameterSerialization.load_checkpoint(ckpt_path)

    def test_reject_invalid_and_incompatible_parameters(self) -> None:
        model = YOLODetector(model_name="yolov8n", num_classes=10, seed=42, device="cpu")
        params = model.get_parameters()

        # Wrong layer count
        with self.assertRaises(ValueError):
            model.set_parameters(params[:-1])

        # Wrong layer shape
        bad_shape = [list(layer) for layer in params]
        bad_shape[0] = bad_shape[0][:-1]
        with self.assertRaises(ValueError):
            model.set_parameters(bad_shape)

        # Non-finite value (NaN / Inf)
        bad_nan = [list(layer) for layer in params]
        bad_nan[0][0] = float("nan")
        with self.assertRaises(ValueError):
            model.set_parameters(bad_nan)

        bad_inf = [list(layer) for layer in params]
        bad_inf[0][0] = float("inf")
        with self.assertRaises(ValueError):
            model.set_parameters(bad_inf)

    def test_weights_checksum_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wpath = Path(tmpdir) / "dummy.pt"
            wpath.write_bytes(b"yolo-weights-payload")
            digest = verify_weights_checksum(wpath)
            self.assertEqual(len(digest), 64)
            self.assertEqual(verify_weights_checksum(wpath, digest), digest)
            with self.assertRaises(ValueError):
                verify_weights_checksum(wpath, "0" * 64)

    def test_training_configuration(self) -> None:
        config = TrainingConfig(
            model_name="yolov8s",
            epochs=3,
            batch_size=8,
            learning_rate=0.005,
            image_size=640,
            device="cpu",
        )
        as_dict = config.to_dict()
        self.assertEqual(as_dict["model_name"], "yolov8s")
        self.assertEqual(as_dict["epochs"], 3)

        restored_config = TrainingConfig.from_dict(as_dict)
        self.assertEqual(restored_config.learning_rate, 0.005)

    def test_dataset_validation_success(self) -> None:
        partition_dir = Path("datasets/processed/partitions/client_0/train")
        if partition_dir.exists():
            stats = VisDroneParser.validate_dataset(
                images_dir=partition_dir / "images",
                annotations_dir=partition_dir / "annotations",
            )
            self.assertGreater(stats["valid_pairs"], 0)
            self.assertGreater(stats["total_boxes"], 0)

    def test_missing_or_corrupt_dataset_handling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_dir = Path(tmpdir)
            empty_img = fake_dir / "images"
            empty_ann = fake_dir / "annotations"
            empty_img.mkdir()
            empty_ann.mkdir()

            with self.assertRaises(DatasetValidationError):
                VisDroneParser.validate_dataset(empty_img, empty_ann)

            corrupt_img = empty_img / "bad.jpg"
            corrupt_img.write_text("this is not an image file")
            bad_ann = empty_ann / "bad.txt"
            bad_ann.write_text("10,10,50,50,1,1,0,0")

            with self.assertRaises(DatasetValidationError):
                VisDroneParser.validate_dataset(empty_img, empty_ann, check_images_readable=True)

            missing_cfg = DatasetConfig(
                images_dir=str(fake_dir / "nonexistent"),
                annotations_dir=str(empty_ann),
            )
            with self.assertRaises(ValueError):
                missing_cfg.validate()

    def test_real_yolo_train_and_evaluate_cpu(self) -> None:
        """
        Real Ultralytics YOLOv8n training & evaluation on a tiny deterministic CPU dataset.
        Verifies:
        - Model parameters actually change after local training
        - samples_trained counts unique images (epoch-invariant)
        - Genuine evaluation metrics (map50, map50_95, precision, recall) are returned
        - Unavailable metrics are None rather than 0.0, and no accuracy_proxy is emitted
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            img_dir, ann_dir = _create_tiny_visdrone_dataset(Path(tmpdir), num_images=2)

            model = YOLODetector(model_name="yolov8n", num_classes=10, seed=42, device="cpu")
            before_params = model.get_parameters()

            train_res = model.train_on_dataset(
                images_dir=str(img_dir),
                annotations_dir=str(ann_dir),
                config=TrainingConfig(epochs=1, batch_size=2, image_size=64, device="cpu"),
                max_samples=2,
            )
            after_params = model.get_parameters()

            self.assertEqual(train_res["samples_trained"], 2)
            self.assertEqual(train_res["total_boxes"], 4)
            self.assertFalse(train_res["is_simulated"])

            # Verify parameters actually changed
            changed = any(
                abs(a - b) > 1e-8
                for la, lb in zip(after_params, before_params, strict=True)
                for a, b in zip(la, lb, strict=True)
            )
            self.assertTrue(changed, "YOLO parameters must change after local training")

            eval_res = model.evaluate_on_dataset(
                images_dir=str(img_dir),
                annotations_dir=str(ann_dir),
                max_samples=2,
                image_size=64,
                batch_size=2,
            )
            self.assertNotIn("accuracy_proxy", eval_res)
            self.assertFalse(eval_res["is_simulated"])
            self.assertEqual(eval_res["images_evaluated"], 2)
            self.assertEqual(eval_res["boxes_evaluated"], 4)
            for key in ("map50", "map50_95", "precision", "recall"):
                self.assertIn(key, eval_res)
                if eval_res[key] is not None:
                    self.assertGreaterEqual(eval_res[key], 0.0)
                    self.assertLessEqual(eval_res[key], 1.0)

    def test_real_visdrone_yolo_train_eval(self) -> None:
        candidates = (
            (Path("datasets/raw/visdrone/images"), Path("datasets/raw/visdrone/annotations")),
            (
                Path("datasets/raw/VisDrone2019-DET-val/images"),
                Path("datasets/raw/VisDrone2019-DET-val/annotations"),
            ),
            (
                Path("datasets/processed/partitions/client_0/train/images"),
                Path("datasets/processed/partitions/client_0/train/annotations"),
            ),
        )
        raw_img, raw_ann = next(
            (
                (images, annotations)
                for images, annotations in candidates
                if images.is_dir() and annotations.is_dir()
            ),
            (None, None),
        )
        self.assertIsNotNone(raw_img, "A real VisDrone dataset or processed partition is required")
        self.assertIsNotNone(raw_ann, "A real VisDrone dataset or processed partition is required")

        model = YOLODetector(model_name="yolov8n", num_classes=10, seed=42, device="cpu")
        train_res = model.train_on_dataset(
            images_dir=raw_img,
            annotations_dir=raw_ann,
            config=TrainingConfig(epochs=1, batch_size=4, image_size=160, device="cpu"),
            max_samples=8,
            client_index=0,
            num_clients=2,
        )
        self.assertGreater(train_res["samples_trained"], 0)
        eval_res = model.evaluate_on_dataset(
            images_dir=raw_img,
            annotations_dir=raw_ann,
            max_samples=4,
            client_index=1,
            num_clients=2,
            image_size=160,
            batch_size=4,
        )
        self.assertIsNotNone(eval_res["map50"])


if __name__ == "__main__":
    unittest.main()
