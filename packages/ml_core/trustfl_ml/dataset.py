"""
VisDrone Dataset Validation and Conversion Tool for YOLO format.

VisDrone annotation line format:
`<bbox_left>,<bbox_top>,<bbox_width>,<bbox_height>,<score>,<object_category>,<truncation>,<occlusion>`

Category mappings:
0: ignored regions
1: pedestrian
2: people
3: bicycle
4: car
5: van
6: truck
7: tricycle
8: awning-tricycle
9: bus
10: motor
11: others

YOLO normalized format:
`<class_id> <x_center_norm> <y_center_norm> <width_norm> <height_norm>`
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

VISDRONE_CLASSES: dict[int, str] = {
    1: "pedestrian",
    2: "people",
    3: "bicycle",
    4: "car",
    5: "van",
    6: "truck",
    7: "tricycle",
    8: "awning-tricycle",
    9: "bus",
    10: "motor",
}


class DatasetValidationError(ValueError):
    """Raised when dataset structure, images or annotations fail validation."""
    pass


class VisDroneParser:
    """Validates and converts VisDrone annotations into normalized YOLO format."""

    @staticmethod
    def parse_annotation_line(
        line: str, img_width: int, img_height: int
    ) -> tuple[int, float, float, float, float] | None:
        """
        Parses a single VisDrone annotation line.
        Returns (yolo_class_id, x_center, y_center, w, h) or None if ignored/invalid.
        """
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if len(parts) < 8:
            return None

        try:
            bbox_left = float(parts[0])
            bbox_top = float(parts[1])
            bbox_width = float(parts[2])
            bbox_height = float(parts[3])
            score = int(parts[4])
            category = int(parts[5])
        except (ValueError, IndexError):
            return None

        # Filter out ignored regions (0) or others (11) or zero-score objects
        if category not in VISDRONE_CLASSES or score == 0:
            return None
        if bbox_width <= 0 or bbox_height <= 0 or img_width <= 0 or img_height <= 0:
            return None

        # Map category (1-10) to 0-indexed YOLO class (0-9)
        class_id = category - 1

        # Compute normalized YOLO coordinates [0, 1]
        x_center = (bbox_left + bbox_width / 2.0) / img_width
        y_center = (bbox_top + bbox_height / 2.0) / img_height
        w_norm = bbox_width / img_width
        h_norm = bbox_height / img_height

        # Clamp bounding box boundaries within [0, 1]
        x_center = max(0.0, min(1.0, x_center))
        y_center = max(0.0, min(1.0, y_center))
        w_norm = max(0.0, min(1.0, w_norm))
        h_norm = max(0.0, min(1.0, h_norm))

        return class_id, x_center, y_center, w_norm, h_norm

    @classmethod
    def validate_dataset(
        cls,
        images_dir: Path | str,
        annotations_dir: Path | str,
        check_images_readable: bool = True,
    ) -> dict[str, int]:
        """
        Validates presence and pairing of images and annotations.
        Raises DatasetValidationError on invalid, corrupted or missing inputs.
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)

        if not img_dir.is_dir():
            raise DatasetValidationError(f"Images directory not found: {img_dir}")
        if not ann_dir.is_dir():
            raise DatasetValidationError(f"Annotations directory not found: {ann_dir}")

        image_files = sorted(
            [f for f in img_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        )
        if not image_files:
            raise DatasetValidationError(f"No valid image files found in {img_dir}")

        valid_pairs = 0
        total_boxes = 0

        for img_path in image_files:
            ann_path = ann_dir / f"{img_path.stem}.txt"
            if not ann_path.is_file():
                continue

            if check_images_readable:
                try:
                    with Image.open(img_path) as im:
                        w, h = im.size
                        if w <= 0 or h <= 0:
                            raise DatasetValidationError(f"Corrupt image dimensions in {img_path}")
                except Exception as e:
                    raise DatasetValidationError(f"Failed to read image {img_path}: {e}") from e
            else:
                w, h = 1920, 1080

            try:
                content = ann_path.read_text(encoding="utf-8")
            except Exception as e:
                raise DatasetValidationError(f"Failed to read annotation file {ann_path}: {e}") from e

            for line in content.splitlines():
                parsed = cls.parse_annotation_line(line, w, h)
                if parsed is not None:
                    total_boxes += 1

            valid_pairs += 1

        if valid_pairs == 0:
            raise DatasetValidationError(f"No matching image-annotation pairs between {img_dir} and {ann_dir}")

        return {
            "total_images": len(image_files),
            "valid_pairs": valid_pairs,
            "total_boxes": total_boxes,
        }

    @classmethod
    def convert_to_yolo(
        cls,
        images_dir: Path | str,
        annotations_dir: Path | str,
        output_images_dir: Path | str,
        output_labels_dir: Path | str,
        max_samples: int | None = None,
    ) -> int:
        """
        Converts VisDrone annotations to YOLO formatted labels and symlinks/copies images.
        """
        img_dir = Path(images_dir)
        ann_dir = Path(annotations_dir)
        out_img_dir = Path(output_images_dir)
        out_lbl_dir = Path(output_labels_dir)

        out_img_dir.mkdir(parents=True, exist_ok=True)
        out_lbl_dir.mkdir(parents=True, exist_ok=True)

        image_files = sorted(
            [f for f in img_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        )
        if max_samples:
            image_files = image_files[:max_samples]

        converted_count = 0
        for img_path in image_files:
            ann_path = ann_dir / f"{img_path.stem}.txt"
            if not ann_path.is_file():
                continue

            try:
                with Image.open(img_path) as im:
                    w, h = im.size
            except Exception:
                continue

            lines = ann_path.read_text(encoding="utf-8").splitlines()
            yolo_lines = []
            for line in lines:
                parsed = cls.parse_annotation_line(line, w, h)
                if parsed:
                    cls_id, xc, yc, bw, bh = parsed
                    yolo_lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")

            # Save YOLO label file
            out_label = out_lbl_dir / f"{img_path.stem}.txt"
            out_label.write_text("\n".join(yolo_lines) + ("\n" if yolo_lines else ""))

            # Link or copy image
            out_image = out_img_dir / img_path.name
            if not out_image.exists():
                try:
                    os.link(str(img_path), str(out_image))
                except OSError:
                    import shutil
                    shutil.copy2(str(img_path), str(out_image))

            converted_count += 1

        return converted_count
