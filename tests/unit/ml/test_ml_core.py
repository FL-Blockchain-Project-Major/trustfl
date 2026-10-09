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


if __name__ == "__main__":
    unittest.main()
