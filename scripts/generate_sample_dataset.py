#!/usr/bin/env python3
"""
Generates a lightweight, valid synthetic raw VisDrone dataset for testing and local protocol demonstration.

Structure created:
  <output_dir>/
    images/
      sample_001.jpg
      ...
    annotations/
      sample_001.txt
      ...
    val/
      images/
      annotations/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_ml_core = _repo_root / "packages" / "ml_core"
if str(_ml_core) not in sys.path:
    sys.path.insert(0, str(_ml_core))

from PIL import Image  # noqa: E402
from trustfl_ml.dataset import resolve_and_validate_dataset  # noqa: E402


def generate_sample_dataset(
    output_dir: Path | str,
    train_samples: int = 10,
    val_samples: int = 3,
    img_width: int = 640,
    img_height: int = 480,
) -> dict[str, int]:
    out_path = Path(output_dir).resolve()
    train_images = out_path / "images"
    train_annotations = out_path / "annotations"
    val_images = out_path / "val" / "images"
    val_annotations = out_path / "val" / "annotations"

    for d in (train_images, train_annotations, val_images, val_annotations):
        d.mkdir(parents=True, exist_ok=True)

    # Generate training samples
    for idx in range(1, train_samples + 1):
        stem = f"sample_{idx:03d}"
        img_file = train_images / f"{stem}.jpg"
        im = Image.new(
            "RGB",
            (img_width, img_height),
            color=((idx * 23) % 256, (idx * 47) % 256, (idx * 83) % 256),
        )
        im.save(img_file, quality=90)

        ann_file = train_annotations / f"{stem}.txt"
        # VisDrone format: bbox_left, bbox_top, bbox_width, bbox_height, score, category, truncation, occlusion
        lines = [
            "50,40,120,90,1,1,0,0",
            "200,150,80,70,1,4,0,0",
            "320,220,100,80,1,5,0,0",
        ]
        ann_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Generate val samples
    for idx in range(1, val_samples + 1):
        stem = f"val_sample_{idx:03d}"
        img_file = val_images / f"{stem}.jpg"
        im = Image.new(
            "RGB",
            (img_width, img_height),
            color=((idx * 31) % 256, (idx * 59) % 256, (idx * 97) % 256),
        )
        im.save(img_file, quality=90)

        ann_file = val_annotations / f"{stem}.txt"
        lines = [
            "40,30,100,80,1,1,0,0",
            "180,120,90,60,1,4,0,0",
        ]
        ann_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stats = resolve_and_validate_dataset(out_path, min_samples=1)
    return stats["stats"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic VisDrone raw sample dataset")
    parser.add_argument(
        "--output-dir",
        default="datasets/sample",
        help="Target directory for generated dataset root",
    )
    parser.add_argument(
        "--train-samples",
        type=int,
        default=10,
        help="Number of training samples to generate",
    )
    parser.add_argument(
        "--val-samples",
        type=int,
        default=3,
        help="Number of validation samples to generate",
    )
    args = parser.parse_args()

    stats = generate_sample_dataset(
        output_dir=args.output_dir,
        train_samples=args.train_samples,
        val_samples=args.val_samples,
    )
    print(f"Generated sample dataset at '{args.output_dir}':")
    print(f"  Valid image-annotation pairs: {stats['valid_pairs']}")
    print(f"  Total bounding boxes: {stats['total_boxes']}")


if __name__ == "__main__":
    main()
