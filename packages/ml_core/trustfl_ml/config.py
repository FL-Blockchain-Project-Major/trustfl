"""
Configuration dataclasses for YOLO training, datasets, and federated rounds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DatasetConfig:
    """Dataset paths and parameters for a training or validation node."""

    images_dir: str
    annotations_dir: str
    val_images_dir: str | None = None
    val_annotations_dir: str | None = None
    dataset_name: str = "VisDrone"
    num_classes: int = 10
    classes: list[str] = field(
        default_factory=lambda: [
            "pedestrian",
            "people",
            "bicycle",
            "car",
            "van",
            "truck",
            "tricycle",
            "awning-tricycle",
            "bus",
            "motor",
        ]
    )

    def validate(self) -> None:
        if not Path(self.images_dir).is_dir():
            raise ValueError(f"Images directory not found: {self.images_dir}")
        if not Path(self.annotations_dir).is_dir():
            raise ValueError(f"Annotations directory not found: {self.annotations_dir}")

    def get_val_dirs(self) -> tuple[str, str]:
        if self.val_images_dir and self.val_annotations_dir:
            return self.val_images_dir, self.val_annotations_dir
        p_img = Path(self.images_dir)
        p_ann = Path(self.annotations_dir)
        if p_img.name == "images" and p_img.parent.name == "train":
            cand_img = p_img.parent.parent / "val" / "images"
            cand_ann = p_ann.parent.parent / "val" / "annotations"
            if cand_img.is_dir() and cand_ann.is_dir():
                return str(cand_img), str(cand_ann)
        return self.images_dir, self.annotations_dir


@dataclass
class TrainingConfig:
    """Hyperparameters and execution configuration for YOLO training."""

    model_name: str = "yolov8n"
    epochs: int = 1
    batch_size: int = 4
    learning_rate: float = 0.01
    image_size: int = 320
    device: str = "cpu"
    seed: int = 42
    patience: int = 5
    optimizer: str = "AdamW"
    weight_decay: float = 0.0005

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ClientNodeConfig:
    """Identity and data configuration for an edge client node."""

    client_id: str
    federation_id: str
    dataset_config: DatasetConfig
    training_config: TrainingConfig = field(default_factory=TrainingConfig)
    model_version: str = "mod_visdrone_v1"
