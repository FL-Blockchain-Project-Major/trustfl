"""
Configuration dataclasses for YOLO training, datasets, and federated rounds.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DatasetConfig:
    """Dataset paths and parameters for a training or validation node."""
    images_dir: str
    annotations_dir: str
    dataset_name: str = "VisDrone"
    num_classes: int = 10
    classes: List[str] = field(
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TrainingConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ClientNodeConfig:
    """Identity and data configuration for an edge client node."""
    client_id: str
    federation_id: str
    dataset_config: DatasetConfig
    training_config: TrainingConfig = field(default_factory=TrainingConfig)
    model_version: str = "mod_visdrone_v1"
