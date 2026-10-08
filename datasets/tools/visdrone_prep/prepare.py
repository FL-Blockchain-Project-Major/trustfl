#!/usr/bin/env python3
"""
Generic Dataset Preparation & Partitioning Tool for VisDrone / YOLO.

Validates raw images and annotations, converts to normalized YOLO labels,
and creates non-overlapping partitions for federated edge clients.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from trustfl_ml.dataset import VisDroneParser


def partition_dataset(
    images_dir: Path | str,
    annotations_dir: Path | str,
    output_dir: Path | str,
    num_clients: int = 3,
    samples_per_client: int = 50,
) -> dict[str, Any]:
    """
    Creates client partitions from source VisDrone dataset.
    Generates:
      output_dir/client_{i}/train/images
      output_dir/client_{i}/train/annotations
      output_dir/client_{i}/val/images
      output_dir/client_{i}/val/annotations
    """
    img_dir = Path(images_dir)
    ann_dir = Path(annotations_dir)
    out_dir = Path(output_dir)

    print(f"==> Validating source dataset at {img_dir} and {ann_dir}...")
    stats = VisDroneParser.validate_dataset(img_dir, ann_dir, check_images_readable=False)
    print(f"Source verified: {stats['valid_pairs']} valid image-annotation pairs ({stats['total_boxes']} bounding boxes).")

    image_files = sorted(
        [f for f in img_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    )

    manifest: dict[str, Any] = {"clients": {}}

    for i in range(num_clients):
        cid = f"client_{i}"
        client_train_dir = out_dir / cid / "train"
        client_val_dir = out_dir / cid / "val"

        (client_train_dir / "images").mkdir(parents=True, exist_ok=True)
        (client_train_dir / "annotations").mkdir(parents=True, exist_ok=True)
        (client_val_dir / "images").mkdir(parents=True, exist_ok=True)
        (client_val_dir / "annotations").mkdir(parents=True, exist_ok=True)

        # Slice non-overlapping subset
        start_idx = i * samples_per_client
        end_idx = start_idx + samples_per_client
        client_images = image_files[start_idx:end_idx]

        train_cutoff = int(len(client_images) * 0.8)
        train_imgs = client_images[:train_cutoff]
        val_imgs = client_images[train_cutoff:]

        # Populate train
        for img in train_imgs:
            ann = ann_dir / f"{img.stem}.txt"
            if ann.is_file():
                dest_img = client_train_dir / "images" / img.name
                dest_ann = client_train_dir / "annotations" / ann.name
                if not dest_img.exists():
                    os.link(str(img), str(dest_img))
                if not dest_ann.exists():
                    shutil.copy2(str(ann), str(dest_ann))

        # Populate val
        for img in val_imgs:
            ann = ann_dir / f"{img.stem}.txt"
            if ann.is_file():
                dest_img = client_val_dir / "images" / img.name
                dest_ann = client_val_dir / "annotations" / ann.name
                if not dest_img.exists():
                    os.link(str(img), str(dest_img))
                if not dest_ann.exists():
                    shutil.copy2(str(ann), str(dest_ann))

        manifest["clients"][cid] = {
            "train_samples": len(train_imgs),
            "val_samples": len(val_imgs),
            "train_images_dir": str(client_train_dir / "images"),
            "train_annotations_dir": str(client_train_dir / "annotations"),
            "val_images_dir": str(client_val_dir / "images"),
            "val_annotations_dir": str(client_val_dir / "annotations"),
        }

    manifest_file = out_dir / "dataset_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    print(f"Dataset partitions prepared for {num_clients} clients in {out_dir}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrustFL VisDrone Dataset Preparation Tool")
    parser.add_argument("--images", default="datasets/raw/visdrone/images", help="Path to raw images")
    parser.add_argument("--annotations", default="datasets/raw/visdrone/annotations", help="Path to raw annotations")
    parser.add_argument("--output", default="datasets/processed/partitions", help="Output path for client partitions")
    parser.add_argument("--clients", type=int, default=3, help="Number of clients")
    parser.add_argument("--samples-per-client", type=int, default=30, help="Samples per client")
    args = parser.parse_args()

    partition_dataset(
        images_dir=args.images,
        annotations_dir=args.annotations,
        output_dir=args.output,
        num_clients=args.clients,
        samples_per_client=args.samples_per_client,
    )
