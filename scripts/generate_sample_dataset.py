#!/usr/bin/env python3
"""
Generates a lightweight, valid synthetic raw VisDrone dataset for testing and local protocol demonstration.

Structure created:
  <output_dir>/
    images/
      sample_001.png (or .jpg)
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
import struct
import sys
import zlib
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_ml_core = _repo_root / "packages" / "ml_core"
if str(_ml_core) not in sys.path:
    sys.path.insert(0, str(_ml_core))

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from trustfl_ml.dataset import resolve_and_validate_dataset
except ImportError:
    resolve_and_validate_dataset = None


def _write_image(path: Path, width: int, height: int, r: int, g: int, b: int) -> None:
    """Save an RGB image using PIL if available, or pure Python PNG otherwise."""
    if Image is not None and path.suffix.lower() in {".jpg", ".jpeg"}:
        im = Image.new("RGB", (width, height), color=(r, g, b))
        im.save(path, quality=90)
        return

    # Standard-library PNG writer (zero external dependencies)
    raw_row = b"\x00" + bytes([r, g, b] * width)
    raw_data = raw_row * height
    compressed = zlib.compress(raw_data)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png_bytes)


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

    ext = ".jpg" if Image is not None else ".png"

    # Generate training samples
    for idx in range(1, train_samples + 1):
        stem = f"sample_{idx:03d}"
        img_file = train_images / f"{stem}{ext}"
        _write_image(
            img_file,
            img_width,
            img_height,
            (idx * 23) % 256,
            (idx * 47) % 256,
            (idx * 83) % 256,
        )

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
        img_file = val_images / f"{stem}{ext}"
        _write_image(
            img_file,
            img_width,
            img_height,
            (idx * 31) % 256,
            (idx * 59) % 256,
            (idx * 97) % 256,
        )

        ann_file = val_annotations / f"{stem}.txt"
        lines = [
            "40,30,100,80,1,1,0,0",
            "180,120,90,60,1,4,0,0",
        ]
        ann_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if resolve_and_validate_dataset is not None:
        stats = resolve_and_validate_dataset(out_path, min_samples=1)
        return stats["stats"]

    return {
        "valid_pairs": train_samples + val_samples,
        "total_boxes": train_samples * 3 + val_samples * 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic VisDrone raw sample dataset")
    parser.add_argument(
        "--out-dir",
        "--output-dir",
        dest="output_dir",
        default="datasets/sample",
        help="Target directory for generated dataset root",
    )
    parser.add_argument(
        "--num-images",
        "--train-samples",
        dest="train_samples",
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
