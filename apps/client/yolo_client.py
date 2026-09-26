"""
TrustFL YOLO Federated Client Implementation.

Each client:
- Obtains its identity, federation ID, and dataset path from configuration.
- Validates local dataset and annotations prior to training.
- Participates in standard Flower lifecycle:
  1. Receives global parameters
  2. Trains locally on VisDrone data partition
  3. Evaluates performance (mAP50, mAP50-95, precision, recall)
  4. Returns serialized parameters & metrics to coordinator
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict

from trustfl_core.flower_app import EvaluateIns, EvaluateRes, FitIns, FitRes, FlowerClient
from trustfl_ml.config import ClientNodeConfig, DatasetConfig, TrainingConfig
from trustfl_ml.dataset import DatasetValidationError, VisDroneParser
from trustfl_ml.yolo_wrapper import YOLOModelWrapper


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

        self.model = YOLOModelWrapper(
            model_name=config.training_config.model_name,
            num_classes=config.dataset_config.num_classes,
            seed=config.training_config.seed,
        )

    def validate_local_data(self) -> Dict[str, int]:
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

        val_metrics = self.model.evaluate_on_dataset(
            images_dir=self.config.dataset_config.images_dir,
            annotations_dir=self.config.dataset_config.annotations_dir,
        )

        num_examples = train_metrics["samples_trained"]
        metrics = {
            "client_id": self.cid,
            "train_loss": train_metrics["train_loss"],
            "val_loss": val_metrics["loss"],
            "map50": val_metrics["map50"],
            "map50_95": val_metrics["map50_95"],
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

        val_metrics = self.model.evaluate_on_dataset(
            images_dir=self.config.dataset_config.images_dir,
            annotations_dir=self.config.dataset_config.annotations_dir,
        )

        return EvaluateRes(
            loss=val_metrics["loss"],
            num_examples=val_metrics["boxes_evaluated"],
            metrics={
                "client_id": self.cid,
                "map50": val_metrics["map50"],
                "map50_95": val_metrics["map50_95"],
                "precision": val_metrics["precision"],
                "recall": val_metrics["recall"],
                "accuracy": val_metrics["map50"],  # Map50 as accuracy proxy for Flower FedAvg
            },
        )
