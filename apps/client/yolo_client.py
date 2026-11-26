"""
TrustFL YOLO Federated Client Implementation.

Each client:
- Obtains its identity, federation ID, and dataset path from configuration.
- Validates local dataset and annotations prior to training.
- Participates in standard Flower lifecycle:
  1. Receives global parameters
  2. Trains locally on VisDrone/YOLO data partition via real Ultralytics YOLO
  3. Evaluates performance on held-out val split (mAP50, mAP50-95, precision, recall)
  4. Returns serialized parameters & metrics to coordinator
"""

from __future__ import annotations

from trustfl_core.flower_app import EvaluateIns, EvaluateRes, FitIns, FitRes, FlowerClient
from trustfl_ml.config import ClientNodeConfig, TrainingConfig
from trustfl_ml.dataset import VisDroneParser
from trustfl_ml.yolo_wrapper import YOLODetector


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

        self.model = YOLODetector(
            model_name=config.training_config.model_name,
            num_classes=config.dataset_config.num_classes,
            seed=config.training_config.seed,
            device=config.training_config.device,
            weights_path=config.training_config.weights_path,
            weights_sha256=config.training_config.weights_sha256,
            pretrained=config.training_config.pretrained,
            class_names=config.dataset_config.classes,
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
        3. Train locally on client's dataset partition
        4. Evaluate on validation split and return updated parameters & metrics
        """
        self.model.set_parameters(ins.parameters)

        train_cfg = TrainingConfig(
            model_name=self.config.training_config.model_name,
            weights_path=self.config.training_config.weights_path,
            weights_sha256=self.config.training_config.weights_sha256,
            pretrained=self.config.training_config.pretrained,
            epochs=int(ins.config.get("local_epochs", self.config.training_config.epochs)),
            batch_size=int(ins.config.get("batch_size", self.config.training_config.batch_size)),
            learning_rate=float(
                ins.config.get("learning_rate", self.config.training_config.learning_rate)
            ),
            image_size=int(ins.config.get("image_size", self.config.training_config.image_size)),
            device=str(ins.config.get("device", self.config.training_config.device)),
            seed=self.config.training_config.seed,
            patience=self.config.training_config.patience,
            optimizer=self.config.training_config.optimizer,
            weight_decay=self.config.training_config.weight_decay,
            workers=self.config.training_config.workers,
            amp=self.config.training_config.amp,
            cache=self.config.training_config.cache,
            conf_threshold=self.config.training_config.conf_threshold,
            iou_threshold=self.config.training_config.iou_threshold,
        )

        val_img_dir, val_ann_dir = self.config.dataset_config.get_val_dirs()
        train_metrics = self.model.train_on_dataset(
            images_dir=self.config.dataset_config.images_dir,
            annotations_dir=self.config.dataset_config.annotations_dir,
            config=train_cfg,
            val_images_dir=val_img_dir,
            val_annotations_dir=val_ann_dir,
        )

        val_metrics = self.model.evaluate_on_dataset(
            images_dir=val_img_dir,
            annotations_dir=val_ann_dir,
            image_size=train_cfg.image_size,
            batch_size=train_cfg.batch_size,
        )

        num_examples = train_metrics["samples_trained"]
        metrics = {
            "client_id": self.cid,
            "train_loss": train_metrics["train_loss"],
            "box_loss": train_metrics["box_loss"],
            "cls_loss": train_metrics["cls_loss"],
            "dfl_loss": train_metrics["dfl_loss"],
            "val_loss": val_metrics["val_loss"],
            "map50": val_metrics["map50"],
            "map50_95": val_metrics["map50_95"],
            "precision": val_metrics["precision"],
            "recall": val_metrics["recall"],
            "total_boxes": train_metrics["total_boxes"],
            "epochs": train_cfg.epochs,
            "model_version": self.model_version,
            "is_simulated": False,
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
        3. Return loss (None if unavailable), example count, and detection metrics
        """
        self.model.set_parameters(ins.parameters)

        val_img_dir, val_ann_dir = self.config.dataset_config.get_val_dirs()
        val_metrics = self.model.evaluate_on_dataset(
            images_dir=val_img_dir,
            annotations_dir=val_ann_dir,
            image_size=self.config.training_config.image_size,
            batch_size=self.config.training_config.batch_size,
        )

        return EvaluateRes(
            loss=val_metrics["loss"],
            num_examples=max(1, val_metrics["images_evaluated"]),
            metrics={
                "client_id": self.cid,
                "map50": val_metrics["map50"],
                "map50_95": val_metrics["map50_95"],
                "precision": val_metrics["precision"],
                "recall": val_metrics["recall"],
                "boxes_evaluated": val_metrics["boxes_evaluated"],
                "images_evaluated": val_metrics["images_evaluated"],
                "is_simulated": False,
            },
        )
