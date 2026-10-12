"""
Unit tests for YOLO, VisDrone dataset validation, training config, and checkpoint management.

Tests:
1. Dataset validation (valid pairs, missing/corrupt annotations)
2. Parameter round trips (serialization, deserialization, hash stability)
3. Model initialization
4. Training configuration
5. Missing / corrupt dataset handling
"""

import tempfile
import unittest
from pathlib import Path

from trustfl_ml.checkpoint import ParameterSerialization
from trustfl_ml.config import DatasetConfig, TrainingConfig
from trustfl_ml.dataset import DatasetValidationError, VisDroneParser
from trustfl_ml.yolo_wrapper import YOLOModelWrapper


class TestMLCore(unittest.TestCase):
    def test_model_initialization(self) -> None:
        model = YOLOModelWrapper(model_name="yolov8n", num_classes=10, seed=42)
        params = model.get_parameters()
        self.assertEqual(len(params), 3)
        self.assertEqual(len(params[0]), 40)  # 10 classes * 4 coordinates
        self.assertEqual(len(params[1]), 16)  # 16 features
        self.assertEqual(len(params[2]), 1)  # 1 bias

    def test_parameter_round_trips(self) -> None:
        model = YOLOModelWrapper(model_name="yolov8n", num_classes=10, seed=123)
        orig_params = model.get_parameters()

        # Serialization to bytes and back
        data_bytes = ParameterSerialization.parameters_to_bytes(orig_params)
        restored = ParameterSerialization.bytes_to_parameters(data_bytes)
        self.assertEqual(len(orig_params), len(restored))
        for layer_orig, layer_res in zip(orig_params, restored, strict=False):
            for v1, v2 in zip(layer_orig, layer_res, strict=False):
                self.assertAlmostEqual(v1, v2, places=6)

        # Checkpoint disk save and load
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            saved_path, sha = ParameterSerialization.save_checkpoint(
                orig_params, ckpt_path, metadata={"epoch": 1, "map50": 0.45}
            )
            self.assertTrue(saved_path.is_file())
            self.assertEqual(len(sha), 64)

            loaded_params, meta = ParameterSerialization.load_checkpoint(ckpt_path)
            self.assertEqual(meta["epoch"], 1)
            self.assertEqual(meta["map50"], 0.45)
            self.assertEqual(len(loaded_params), len(orig_params))

    def test_training_configuration(self) -> None:
        config = TrainingConfig(
            model_name="yolov8s",
            epochs=3,
            batch_size=8,
            learning_rate=0.005,
            image_size=640,
        )
        as_dict = config.to_dict()
        self.assertEqual(as_dict["model_name"], "yolov8s")
        self.assertEqual(as_dict["epochs"], 3)

        restored_config = TrainingConfig.from_dict(as_dict)
        self.assertEqual(restored_config.learning_rate, 0.005)

    def test_dataset_validation_success(self) -> None:
        # Validate against the real partitioned VisDrone dataset
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

            # Empty dataset raises DatasetValidationError
            with self.assertRaises(DatasetValidationError):
                VisDroneParser.validate_dataset(empty_img, empty_ann)

            # Corrupt image raises DatasetValidationError
            corrupt_img = empty_img / "bad.jpg"
            corrupt_img.write_text("this is not an image file")
            bad_ann = empty_ann / "bad.txt"
            bad_ann.write_text("10,10,50,50,1,1,0,0")

            with self.assertRaises(DatasetValidationError):
                VisDroneParser.validate_dataset(empty_img, empty_ann, check_images_readable=True)

            # Non-existent directory handling in DatasetConfig
            missing_cfg = DatasetConfig(
                images_dir=str(fake_dir / "nonexistent"),
                annotations_dir=str(empty_ann),
            )
            with self.assertRaises(ValueError):
                missing_cfg.validate()

    def test_samples_trained_is_epoch_invariant(self) -> None:
        """
        samples_trained must count unique images, not image×epoch pairs.
        Training for 2 epochs must report the same value as training for 1 epoch.
        """
        import tempfile

        from PIL import Image as PILImage
        from trustfl_ml.yolo_wrapper import SimulatedDetector

        # Build a tiny synthetic dataset: 3 images with valid annotations.
        with tempfile.TemporaryDirectory() as tmpdir:
            img_dir = Path(tmpdir) / "images"
            ann_dir = Path(tmpdir) / "annotations"
            img_dir.mkdir()
            ann_dir.mkdir()

            for i in range(3):
                img = PILImage.new("RGB", (64, 64), color=(i * 80, 0, 0))
                img.save(img_dir / f"img{i:03d}.jpg")
                # VisDrone CSV format:
                # bbox_left,bbox_top,bbox_width,bbox_height,score,category,truncation,occlusion
                # category=1 (pedestrian), score=1 (non-ignored)
                (ann_dir / f"img{i:03d}.txt").write_text("10,10,20,20,1,1,0,0\n")

            model1 = SimulatedDetector(seed=42)
            res1 = model1.train_on_dataset(
                images_dir=str(img_dir),
                annotations_dir=str(ann_dir),
                config=TrainingConfig(epochs=1),
                max_samples=10,
            )

            model2 = SimulatedDetector(seed=42)
            res2 = model2.train_on_dataset(
                images_dir=str(img_dir),
                annotations_dir=str(ann_dir),
                config=TrainingConfig(epochs=2),
                max_samples=10,
            )

            self.assertEqual(
                res1["samples_trained"],
                res2["samples_trained"],
                "samples_trained must be epoch-invariant (unique images, not image×epochs)",
            )
            # Must equal the number of images, not images × epochs.
            self.assertEqual(res1["samples_trained"], 3)


if __name__ == "__main__":
    unittest.main()
