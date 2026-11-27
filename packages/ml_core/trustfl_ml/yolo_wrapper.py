"""
Real Ultralytics YOLO wrapper for TrustFL federated object detection.

Provides:
- Genuine Ultralytics YOLOv8 model initialization (from verified .pt weights or .yaml architecture)
- Deterministic PyTorch state_dict parameter extraction, validation, and loading
- Local YOLO training on VisDrone/YOLO datasets
- Genuine object-detection evaluation (mAP50, mAP50-95, precision, recall, losses)
- Strict rejection of incompatible architectures, malformed shapes, and non-finite tensors
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from PIL import Image
from ultralytics import YOLO

from trustfl_ml.config import TrainingConfig
from trustfl_ml.dataset import VISDRONE_CLASSES, VisDroneParser

logger = logging.getLogger(__name__)

# Optional registry of known-good SHA-256 digests for provisioned weight files.
# Operators can also supply an explicit expected digest via TrainingConfig.weights_sha256
# or FL_YOLO_WEIGHTS_SHA256.
KNOWN_WEIGHT_SHA256: dict[str, str] = {}

# Process-local cache of base Ultralytics model YAML dicts to avoid
# constructing a throwaway DetectionModel on every YOLODetector init.
_BASE_YAML_CACHE: dict[str, dict[str, Any]] = {}


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_weights_checksum(weights_path: Path | str, expected_sha256: str | None = None) -> str:
    """Verify SHA-256 checksum of a weights file if an expected digest is provided."""
    path = Path(weights_path)
    if not path.is_file():
        raise FileNotFoundError(f"YOLO weights file not found: {path}")
    actual = compute_file_sha256(path)
    expected = expected_sha256 or KNOWN_WEIGHT_SHA256.get(path.name)
    if expected:
        norm_expected = expected.lower().removeprefix("sha256:")
        if actual.lower() != norm_expected:
            raise ValueError(
                f"YOLO weights checksum mismatch for {path}: expected {norm_expected}, got {actual}"
            )
    return actual


def resolve_device(device: str = "cpu") -> str:
    """Resolve and validate the target compute device ('cpu', 'cuda', 'cuda:0', 'mps', 'auto')."""
    dev = (device or "cpu").strip().lower()
    if dev == "auto":
        if torch.cuda.is_available():
            return "0"
        return "cpu"
    if dev.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError(f"Requested CUDA device '{device}' but CUDA is not available")
        if ":" in dev:
            return dev.split(":", 1)[1]
        return "0"
    if dev == "mps":
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise RuntimeError("Requested MPS device but MPS is not available")
        return "mps"
    return "cpu"


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _finite_float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class YOLODetector:
    """
    Real Ultralytics YOLO detector for federated object detection.
    """

    def __init__(
        self,
        model_name: str = "yolov8n",
        num_classes: int = 10,
        seed: int = 42,
        device: str = "cpu",
        weights_path: str | Path | None = None,
        weights_sha256: str | None = None,
        pretrained: bool = False,
        class_names: list[str] | None = None,
    ) -> None:
        if num_classes < 1:
            raise ValueError(f"num_classes must be >= 1, got {num_classes}")

        self.model_name = model_name
        self.num_classes = num_classes
        self.seed = seed
        self.device = resolve_device(device)
        self.weights_path = str(weights_path) if weights_path else None
        self.weights_sha256 = weights_sha256
        self.pretrained = pretrained
        self.class_names = class_names or [
            VISDRONE_CLASSES.get(i + 1, f"class_{i}") for i in range(num_classes)
        ]
        if len(self.class_names) != num_classes:
            self.class_names = [f"class_{i}" for i in range(num_classes)]

        _seed_everything(seed)
        self._temp_cfg_dir: tempfile.TemporaryDirectory[str] | None = None
        self.model = self._load_yolo_model()
        self._init_param_spec()

    def _load_yolo_model(self) -> YOLO:
        """Load Ultralytics YOLO from verified weights or architecture YAML with exact num_classes."""
        if self.weights_path:
            wpath = Path(self.weights_path)
            verify_weights_checksum(wpath, self.weights_sha256)
            yolo = YOLO(str(wpath))
            return yolo

        if self.pretrained:
            pt_name = (
                self.model_name if self.model_name.endswith(".pt") else f"{self.model_name}.pt"
            )
            yolo = YOLO(pt_name)
            if self.weights_sha256 and getattr(yolo, "ckpt_path", None):
                verify_weights_checksum(yolo.ckpt_path, self.weights_sha256)
            return yolo

        # Initialize from bundled Ultralytics architecture YAML with exact nc=self.num_classes
        # so the Detect head matches the target dataset from round 0 (no network download).
        base_yaml = (
            self.model_name if self.model_name.endswith(".yaml") else f"{self.model_name}.yaml"
        )
        if base_yaml not in _BASE_YAML_CACHE:
            probe = YOLO(base_yaml)
            _BASE_YAML_CACHE[base_yaml] = dict(probe.model.yaml)
        cfg_dict = dict(_BASE_YAML_CACHE[base_yaml])
        cfg_dict["nc"] = self.num_classes

        self._temp_cfg_dir = tempfile.TemporaryDirectory(prefix="trustfl_yolo_cfg_")
        custom_yaml = (
            Path(self._temp_cfg_dir.name) / f"{Path(base_yaml).stem}_nc{self.num_classes}.yaml"
        )
        custom_yaml.write_text(yaml.safe_dump(cfg_dict, sort_keys=False), encoding="utf-8")
        return YOLO(str(custom_yaml))

    def _init_param_spec(self) -> None:
        """Record ordered floating-point state_dict keys, shapes, and dtypes."""
        sd = self.model.model.state_dict()
        self._param_keys: list[str] = []
        self._param_shapes: list[tuple[int, ...]] = []
        self._param_dtypes: list[torch.dtype] = []
        for k, v in sd.items():
            if isinstance(v, torch.Tensor) and v.is_floating_point():
                self._param_keys.append(k)
                self._param_shapes.append(tuple(v.shape))
                self._param_dtypes.append(v.dtype)
        if not self._param_keys:
            raise RuntimeError("Loaded YOLO model has no floating-point parameters")

    def parameter_count(self) -> int:
        """Total number of scalar floating-point parameters."""
        return sum(math.prod(shape) for shape in self._param_shapes)

    def get_parameters(self) -> list[list[float]]:
        """Extract all floating-point state_dict tensors as flat lists of finite floats."""
        sd = self.model.model.state_dict()
        params: list[list[float]] = []
        for k in self._param_keys:
            tensor = sd[k].detach().cpu().to(torch.float32).reshape(-1)
            if not torch.isfinite(tensor).all():
                raise ValueError(f"Non-finite parameter tensor detected in '{k}'")
            params.append(tensor.tolist())
        return params

    def set_parameters(self, parameters: list[list[float]]) -> None:
        """Validate and load flat parameter lists into the YOLO model state_dict."""
        if not isinstance(parameters, list):
            raise ValueError("Parameters must be a list of layer float lists")
        if len(parameters) != len(self._param_keys):
            raise ValueError(
                f"Parameter layer mismatch: expected {len(self._param_keys)}, got {len(parameters)}"
            )

        current_sd = self.model.model.state_dict()
        new_sd: dict[str, torch.Tensor] = dict(current_sd)

        for idx, (key, shape, dtype, layer) in enumerate(
            zip(self._param_keys, self._param_shapes, self._param_dtypes, parameters, strict=True)
        ):
            if not isinstance(layer, (list, tuple)):
                raise ValueError(f"Parameter layer {idx} ('{key}') must be a list of floats")
            expected_len = math.prod(shape)
            if len(layer) != expected_len:
                raise ValueError(
                    f"Shape mismatch at layer {idx} ('{key}'): "
                    f"expected {expected_len} elements for {shape}, got {len(layer)}"
                )
            tensor = torch.tensor(layer, dtype=torch.float32)
            if not torch.isfinite(tensor).all():
                raise ValueError(f"Non-finite values (NaN/Inf) in layer {idx} ('{key}')")
            target_device = current_sd[key].device
            new_sd[key] = tensor.reshape(shape).to(device=target_device, dtype=dtype)

        self.model.model.load_state_dict(new_sd, strict=True)

    @staticmethod
    def _select_partition_images(
        images_dir: Path,
        max_samples: int | None,
        client_index: int,
        num_clients: int,
    ) -> list[Path]:
        all_images = sorted(
            f for f in images_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if num_clients > 1:
            eff_idx = client_index % num_clients
            selected = [f for i, f in enumerate(all_images) if i % num_clients == eff_idx]
        else:
            selected = all_images
        if max_samples is not None and max_samples > 0:
            selected = selected[:max_samples]
        return selected

    @staticmethod
    def _convert_partition_to_yolo(
        image_files: list[Path],
        annotations_dir: Path,
        out_images_dir: Path,
        out_labels_dir: Path,
    ) -> tuple[int, int]:
        """Convert VisDrone (or already-YOLO) annotations into Ultralytics YOLO layout."""
        out_images_dir.mkdir(parents=True, exist_ok=True)
        out_labels_dir.mkdir(parents=True, exist_ok=True)

        samples_count = 0
        total_boxes = 0

        for img_path in image_files:
            ann_path = annotations_dir / f"{img_path.stem}.txt"
            if not ann_path.is_file():
                continue
            with Image.open(img_path) as im:
                w, h = im.size
            if w <= 0 or h <= 0:
                continue

            yolo_lines: list[str] = []
            for raw_line in ann_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if "," in line:
                    parsed = VisDroneParser.parse_annotation_line(line, w, h)
                    if parsed is not None:
                        cls_id, xc, yc, bw, bh = parsed
                        yolo_lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
                else:
                    parts = line.split()
                    if len(parts) == 5:
                        try:
                            cls_id = int(parts[0])
                            xc, yc, bw, bh = (
                                float(parts[1]),
                                float(parts[2]),
                                float(parts[3]),
                                float(parts[4]),
                            )
                            if 0 <= xc <= 1 and 0 <= yc <= 1 and 0 < bw <= 1 and 0 < bh <= 1:
                                yolo_lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
                        except ValueError:
                            continue

            if not yolo_lines:
                continue

            out_label = out_labels_dir / f"{img_path.stem}.txt"
            out_label.write_text("\n".join(yolo_lines) + "\n", encoding="utf-8")

            out_image = out_images_dir / img_path.name
            if not out_image.exists():
                try:
                    os.link(str(img_path), str(out_image))
                except OSError:
                    shutil.copy2(str(img_path), str(out_image))

            samples_count += 1
            total_boxes += len(yolo_lines)

        return samples_count, total_boxes

    def _write_data_yaml(self, root_dir: Path, has_val: bool = True) -> Path:
        data_cfg = {
            "path": str(root_dir.resolve()),
            "train": "images/train",
            "val": "images/val" if has_val else "images/train",
            "nc": self.num_classes,
            "names": dict(enumerate(self.class_names)),
        }
        yaml_path = root_dir / "data.yaml"
        yaml_path.write_text(yaml.safe_dump(data_cfg, sort_keys=False), encoding="utf-8")
        return yaml_path

    def train_on_dataset(
        self,
        images_dir: Path | str,
        annotations_dir: Path | str,
        config: TrainingConfig,
        max_samples: int = 20,
        client_index: int = 0,
        num_clients: int = 1,
        val_images_dir: Path | str | None = None,
        val_annotations_dir: Path | str | None = None,
    ) -> dict[str, Any]:
        """
        Executes real local Ultralytics YOLO training on the client's dataset partition.
        Returns genuine training metrics (losses, samples_trained, total_boxes, epochs).
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)
        selected_train = self._select_partition_images(
            img_dir, max_samples, client_index, num_clients
        )
        if not selected_train:
            raise ValueError(f"No training images selected from {img_dir}")

        with tempfile.TemporaryDirectory(prefix="trustfl_yolo_train_") as tmpdir:
            work_dir = Path(tmpdir)
            samples_count, total_boxes = self._convert_partition_to_yolo(
                selected_train,
                ann_dir,
                work_dir / "images" / "train",
                work_dir / "labels" / "train",
            )
            if samples_count == 0:
                raise ValueError(f"No valid annotated training samples found in {img_dir}")

            has_val = False
            if val_images_dir and val_annotations_dir:
                v_img_dir = Path(val_images_dir)
                v_ann_dir = Path(val_annotations_dir)
                if v_img_dir.is_dir() and v_ann_dir.is_dir():
                    selected_val = self._select_partition_images(
                        v_img_dir, max_samples, client_index, num_clients
                    )
                    if selected_val:
                        val_count, _ = self._convert_partition_to_yolo(
                            selected_val,
                            v_ann_dir,
                            work_dir / "images" / "val",
                            work_dir / "labels" / "val",
                        )
                        has_val = val_count > 0

            data_yaml = self._write_data_yaml(work_dir, has_val=has_val)
            device = resolve_device(config.device or self.device)
            _seed_everything(config.seed)

            # Persist current in-memory federated weights to a temporary .pt checkpoint so
            # Ultralytics DetectionTrainer starts from the exact aggregated global model
            # rather than re-initializing from the architecture YAML.
            init_ckpt = work_dir / "round_init.pt"
            self.model.save(str(init_ckpt))
            round_yolo = YOLO(str(init_ckpt))

            results = round_yolo.train(
                data=str(data_yaml),
                epochs=config.epochs,
                imgsz=config.image_size,
                batch=min(config.batch_size, samples_count),
                lr0=config.learning_rate,
                device=device,
                seed=config.seed,
                workers=config.workers,
                optimizer=config.optimizer,
                weight_decay=config.weight_decay,
                patience=config.patience,
                amp=config.amp,
                cache=config.cache,
                val=has_val,
                plots=False,
                save=False,
                verbose=False,
                project=str(work_dir / "runs"),
                name="train",
                exist_ok=True,
            )

            # Extract genuine training losses and sync trained weights back to self.model.model
            trainer = getattr(round_yolo, "trainer", None)
            box_loss: float | None = None
            cls_loss: float | None = None
            dfl_loss: float | None = None
            train_loss: float | None = None

            if trainer is not None:
                trained_nn = getattr(trainer, "model", None)
                if trained_nn is not None:
                    self.model.model.load_state_dict(trained_nn.state_dict(), strict=True)
                loss_items = getattr(trainer, "loss_items", None)
                if isinstance(loss_items, dict):
                    box_loss = _finite_float_or_none(
                        loss_items.get("train/box_loss", loss_items.get("box_loss"))
                    )
                    cls_loss = _finite_float_or_none(
                        loss_items.get("train/cls_loss", loss_items.get("cls_loss"))
                    )
                    dfl_loss = _finite_float_or_none(
                        loss_items.get("train/dfl_loss", loss_items.get("dfl_loss"))
                    )
                    parts = [x for x in (box_loss, cls_loss, dfl_loss) if x is not None]
                    if parts:
                        train_loss = round(sum(parts), 6)
                elif (
                    loss_items is not None
                    and hasattr(loss_items, "__len__")
                    and len(loss_items) >= 3
                ):
                    try:
                        box_loss = _finite_float_or_none(loss_items[0])
                        cls_loss = _finite_float_or_none(loss_items[1])
                        dfl_loss = _finite_float_or_none(loss_items[2])
                        parts = [x for x in (box_loss, cls_loss, dfl_loss) if x is not None]
                        if parts:
                            train_loss = round(sum(parts), 6)
                    except (KeyError, IndexError, TypeError):
                        pass

            if train_loss is None and results is not None:
                res_dict = getattr(results, "results_dict", {}) or {}
                b = _finite_float_or_none(res_dict.get("train/box_loss"))
                c = _finite_float_or_none(res_dict.get("train/cls_loss"))
                d = _finite_float_or_none(res_dict.get("train/dfl_loss"))
                box_loss = box_loss if box_loss is not None else b
                cls_loss = cls_loss if cls_loss is not None else c
                dfl_loss = dfl_loss if dfl_loss is not None else d
                parts = [x for x in (box_loss, cls_loss, dfl_loss) if x is not None]
                if parts:
                    train_loss = round(sum(parts), 6)

            return {
                "train_loss": train_loss,
                "box_loss": box_loss,
                "cls_loss": cls_loss,
                "dfl_loss": dfl_loss,
                "samples_trained": samples_count,
                "total_boxes": total_boxes,
                "epochs": config.epochs,
                "model_name": self.model_name,
                "device": device,
                "is_simulated": False,
            }

    def evaluate_on_dataset(
        self,
        images_dir: Path | str,
        annotations_dir: Path | str,
        max_samples: int = 15,
        client_index: int = 0,
        num_clients: int = 1,
        image_size: int = 320,
        batch_size: int = 4,
        conf_threshold: float = 0.001,
        iou_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """
        Evaluates current YOLO parameters on the validation partition using Ultralytics validator.
        Returns genuine mAP50, mAP50-95, precision, recall, and val_loss (None if unavailable).
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)
        selected_val = self._select_partition_images(
            img_dir, max_samples, client_index, num_clients
        )
        if not selected_val:
            raise ValueError(f"No validation images selected from {img_dir}")

        with tempfile.TemporaryDirectory(prefix="trustfl_yolo_val_") as tmpdir:
            work_dir = Path(tmpdir)
            val_count, total_boxes = self._convert_partition_to_yolo(
                selected_val,
                ann_dir,
                work_dir / "images" / "val",
                work_dir / "labels" / "val",
            )
            if val_count == 0:
                raise ValueError(f"No valid annotated validation samples found in {img_dir}")

            data_yaml = self._write_data_yaml(work_dir, has_val=True)
            # Evaluate on a temporary checkpoint copy so val() layer fusion never mutates self.model.model
            eval_ckpt = work_dir / "eval_model.pt"
            self.model.save(str(eval_ckpt))
            eval_yolo = YOLO(str(eval_ckpt))
            val_results = eval_yolo.val(
                data=str(data_yaml),
                imgsz=image_size,
                batch=min(batch_size, val_count),
                device=self.device,
                workers=0,
                conf=conf_threshold,
                iou=iou_threshold,
                plots=False,
                save_json=False,
                verbose=False,
                project=str(work_dir / "runs"),
                name="val",
                exist_ok=True,
            )

            box_metrics = getattr(val_results, "box", None)
            res_dict = getattr(val_results, "results_dict", {}) or {}

            map50 = _finite_float_or_none(
                getattr(box_metrics, "map50", None)
                if box_metrics is not None
                else res_dict.get("metrics/mAP50(B)")
            )
            map50_95 = _finite_float_or_none(
                getattr(box_metrics, "map", None)
                if box_metrics is not None
                else res_dict.get("metrics/mAP50-95(B)")
            )
            precision = _finite_float_or_none(
                getattr(box_metrics, "mp", None)
                if box_metrics is not None
                else res_dict.get("metrics/precision(B)")
            )
            recall = _finite_float_or_none(
                getattr(box_metrics, "mr", None)
                if box_metrics is not None
                else res_dict.get("metrics/recall(B)")
            )

            # Ultralytics standalone val() does not always compute validation loss;
            # keep None rather than substituting 0.0 when unavailable.
            vb = _finite_float_or_none(res_dict.get("val/box_loss"))
            vc = _finite_float_or_none(res_dict.get("val/cls_loss"))
            vd = _finite_float_or_none(res_dict.get("val/dfl_loss"))
            val_loss_parts = [x for x in (vb, vc, vd) if x is not None]
            val_loss = round(sum(val_loss_parts), 6) if val_loss_parts else None

            return {
                "loss": val_loss,
                "val_loss": val_loss,
                "map50": map50,
                "map50_95": map50_95,
                "precision": precision,
                "recall": recall,
                "boxes_evaluated": total_boxes,
                "images_evaluated": val_count,
                "is_simulated": False,
            }


# Default YOLO model wrapper alias
YOLOModelWrapper = YOLODetector
