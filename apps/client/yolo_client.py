"""
TrustFL YOLO Federated Client Implementation.

Each client:
- Obtains its identity, federation ID, and dataset path from configuration.
- Validates local dataset and annotations prior to training.
- Participates in standard Flower lifecycle:
  1. Receives global parameters
  2. Trains locally on VisDrone data partition (via SimulatedDetector — NOT real YOLO)
  3. Evaluates performance on held-out val split (accuracy_proxy, precision, recall)
  4. Returns serialized parameters & metrics to coordinator

NOTE: The ``SimulatedDetector`` class (aliased as ``YOLOModelWrapper``) is a pure-Python
simulation that does NOT compute real mAP50 or mAP50-95. See
``packages/ml_core/trustfl_ml/yolo_wrapper.py`` for the full disclaimer.
"""

from __future__ import annotations

from trustfl_core.flower_app import EvaluateIns, EvaluateRes, FitIns, FitRes, FlowerClient
from trustfl_ml.config import ClientNodeConfig
from trustfl_ml.dataset import VisDroneParser
from trustfl_ml.yolo_wrapper import SimulatedDetector


class TrustFLYOLOClient(FlowerClient):
    """
    Edge YOLO worker client configured via ClientNodeConfig.
    """

    def __init__(self, config: ClientNodeConfig) -> None:
        self.config = config
        self.cid = config.client_id
        self.federation_id = config.federation_id
        self.model_version = config.model_version

        # Validate dataset exists
        self.config.dataset_config.validate()

        self.model = SimulatedDetector(
            model_name=config.training_config.model_name,
            num_classes=config.dataset_config.num_classes,
            seed=config.training_config.seed,
        )

    def validate_local_data(self) -> dict[str, int]:
        """Validates that local client images and annotations are sound."""
        return VisDroneParser.validate_dataset(
            images_dir=self.config.dataset_config.images_dir,
            annotations_dir=self.config.dataset_config.annotations_dir,
            check_images_readable=False,
        )

    def fit(self, ins: FitIns) -> FitRes:
        """
        1. Receive global parameters
        2. Set local YOLO parameters
        3. Train locally on client's VisDrone partition
        4. Return updated parameters and metrics
        """
        self.model.set_parameters(ins.parameters)

        train_metrics = self.model.train_on_dataset(
            images_dir=self.config.dataset_config.images_dir,
            annotations_dir=self.config.dataset_config.annotations_dir,
            config=self.config.training_config,
        )

        val_img_dir, val_ann_dir = self.config.dataset_config.get_val_dirs()
        val_metrics = self.model.evaluate_on_dataset(
            images_dir=val_img_dir,
            annotations_dir=val_ann_dir,
        )

        num_examples = train_metrics["samples_trained"]
        metrics = {
            "client_id": self.cid,
            "train_loss": train_metrics["train_loss"],
            "val_loss": val_metrics["loss"],
            "accuracy_proxy": val_metrics["accuracy_proxy"],
            "precision": val_metrics["precision"],
            "recall": val_metrics["recall"],
            "total_boxes": train_metrics["total_boxes"],
            "epochs": self.config.training_config.epochs,
            "model_version": self.model_version,
        }

        return FitRes(
            parameters=self.model.get_parameters(),
            num_examples=max(1, num_examples),
            metrics=metrics,
        )

    def evaluate(self, ins: EvaluateIns) -> EvaluateRes:
        """
        1. Receive global parameters
        2. Evaluate parameters on client validation partition
        3. Return loss, example count, and detection metrics
        """
        self.model.set_parameters(ins.parameters)

        val_img_dir, val_ann_dir = self.config.dataset_config.get_val_dirs()
        val_metrics = self.model.evaluate_on_dataset(
            images_dir=val_img_dir,
            annotations_dir=val_ann_dir,
        )

        return EvaluateRes(
            loss=val_metrics["loss"],
            num_examples=val_metrics["boxes_evaluated"],
            metrics={
                "client_id": self.cid,
                "accuracy_proxy": val_metrics["accuracy_proxy"],
                "precision": val_metrics["precision"],
                "recall": val_metrics["recall"],
                "accuracy": val_metrics["accuracy_proxy"],
            },
        )
