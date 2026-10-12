"""
SimulatedDetector — lightweight simulated object detector with pure-Python fallback.

NOTE: This is NOT a real YOLO model. ``HAVE_ULTRALYTICS`` controls whether the real
Ultralytics package is importable; the bundled ``SimulatedDetector`` class does NOT use
it and does NOT compute real mAP. Reported metrics (``accuracy_proxy``, ``precision``,
``recall``) are formula-derived proxies for deterministic federated-learning testing
only. Do not interpret them as mAP50 or mAP50-95.

Provides:
- Deterministic simulated model initialization
- Local training simulation on VisDrone/YOLO datasets (gradient-step approximation)
- Validation via accuracy_proxy (NOT mAP)
- Parameter extraction & update for FedAvg aggregation
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from PIL import Image

from trustfl_ml.config import TrainingConfig
from trustfl_ml.dataset import VisDroneParser

try:
    import ultralytics  # noqa: F401

    HAVE_ULTRALYTICS = True
except ImportError:
    HAVE_ULTRALYTICS = False


class SimulatedDetector:
    """
    Built-in lightweight simulated object detector for deterministic edge evaluation.
    Computes parameter updates and returns an accuracy_proxy metric.
    """

    def __init__(
        self,
        model_name: str = "simulated_detector",
        num_classes: int = 10,
        seed: int = 42,
    ) -> None:
        self.model_name = model_name
        self.num_classes = num_classes
        self.seed = seed
        self.rng = random.Random(seed)

        # Parameter tensors: [detection_heads_weights, backbone_weights, biases]
        # Dimension: [10 classes x 4 coordinates, 16 features, 1 bias]
        self.weights: list[list[float]] = [
            [self.rng.uniform(-0.05, 0.05) for _ in range(num_classes * 4)],
            [self.rng.uniform(-0.05, 0.05) for _ in range(16)],
            [0.0],
        ]

    def get_parameters(self) -> list[list[float]]:
        """Extracts parameters as list of float arrays."""
        return [list(layer) for layer in self.weights]

    def set_parameters(self, parameters: list[list[float]]) -> None:
        """Sets model parameters."""
        if len(parameters) != len(self.weights):
            raise ValueError(
                f"Parameter layer mismatch: expected {len(self.weights)}, got {len(parameters)}"
            )
        self.weights = [list(layer) for layer in parameters]

    def train_on_dataset(
        self,
        images_dir: Path | str,
        annotations_dir: Path | str,
        config: TrainingConfig,
        max_samples: int = 20,
    ) -> dict[str, Any]:
        """
        Executes local training on client VisDrone data.
        Returns training metrics: loss, samples_trained, duration, etc.
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)

        image_files = sorted(
            [f for f in img_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        )[:max_samples]

        total_loss = 0.0
        samples_count = 0
        total_boxes = 0

        # Training loop over client's images
        for _epoch in range(config.epochs):
            epoch_loss = 0.0
            for img_path in image_files:
                ann_path = ann_dir / f"{img_path.stem}.txt"
                if not ann_path.is_file():
                    continue

                with Image.open(img_path) as im:
                    w, h = im.size

                boxes = []
                for line in ann_path.read_text(encoding="utf-8").splitlines():
                    parsed = VisDroneParser.parse_annotation_line(line, w, h)
                    if parsed:
                        boxes.append(parsed)

                if not boxes:
                    continue

                samples_count += 1
                total_boxes += len(boxes)

                # Compute gradient updates on detection heads
                loss_contrib = 0.0
                for cls_id, xc, yc, bw, bh in boxes:
                    # Model prediction error simulation
                    weight_idx = (cls_id * 4) % len(self.weights[0])
                    current_w = self.weights[0][weight_idx]
                    target = (xc + yc + bw + bh) / 4.0
                    err = current_w - target

                    # Gradient step
                    grad = err * config.learning_rate / (len(boxes) * max(1, config.batch_size))
                    self.weights[0][weight_idx] -= grad
                    loss_contrib += err * err

                epoch_loss += loss_contrib / len(boxes)

            total_loss = epoch_loss / max(1, len(image_files))

        return {
            "train_loss": round(total_loss, 5),
            "samples_trained": samples_count,
            "total_boxes": total_boxes,
            "epochs": config.epochs,
            "model_name": self.model_name,
        }

    def evaluate_on_dataset(
        self,
        images_dir: Path | str,
        annotations_dir: Path | str,
        max_samples: int = 15,
    ) -> dict[str, float]:
        """
        Evaluates current parameters against the validation partition.
        Returns accuracy_proxy, precision, recall, loss, and boxes_evaluated.
        NOTE: These are simulated metrics, NOT real mAP50 or mAP50-95.
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)

        image_files = sorted(
            [f for f in img_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        )[:max_samples]

        total_err = 0.0
        total_eval_boxes = 0

        for img_path in image_files:
            ann_path = ann_dir / f"{img_path.stem}.txt"
            if not ann_path.is_file():
                continue

            with Image.open(img_path) as im:
                w, h = im.size

            for line in ann_path.read_text(encoding="utf-8").splitlines():
                parsed = VisDroneParser.parse_annotation_line(line, w, h)
                if parsed:
                    cls_id, xc, yc, bw, bh = parsed
                    weight_idx = (cls_id * 4) % len(self.weights[0])
                    current_w = self.weights[0][weight_idx]
                    target = (xc + yc + bw + bh) / 4.0
                    total_err += abs(current_w - target)
                    total_eval_boxes += 1

        avg_err = total_err / max(1, total_eval_boxes)
        loss = round(avg_err, 4)

        # Simulation: parameter distance to targets produces an accuracy proxy
        accuracy_proxy = max(0.0, min(1.0, 1.0 - (loss * 2.0)))
        precision = round(accuracy_proxy * 0.88, 4)
        recall = round(accuracy_proxy * 0.82, 4)

        return {
            "loss": loss,
            "accuracy_proxy": accuracy_proxy,
            "precision": precision,
            "recall": recall,
            "boxes_evaluated": total_eval_boxes,
        }


# Backwards compatibility alias
YOLOModelWrapper = SimulatedDetector
