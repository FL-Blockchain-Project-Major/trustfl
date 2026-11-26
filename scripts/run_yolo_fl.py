#!/usr/bin/env python3
"""
Executes a federated learning run on real VisDrone image & annotation data
using the Flower ServerApp/ClientApp and real Ultralytics YOLOv8 architecture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from trustfl_core.flower_app import ClientApp
from trustfl_ml.config import ClientNodeConfig, DatasetConfig, TrainingConfig
from trustfl_ml.yolo_wrapper import YOLOModelWrapper

from apps.client.yolo_client import TrustFLYOLOClient
from apps.coordinator.coordinator import create_server_app


def _fmt_metric(val: float | None, fmt: str = ".4f") -> str:
    if val is None:
        return "N/A"
    return format(val, fmt)


def main() -> None:
    print("======================================================================")
    print("TrustFL Real Workload: Federated Ultralytics YOLO on VisDrone Dataset")
    print("======================================================================")

    model_name = os.getenv("FL_YOLO_MODEL", "yolov8n")
    weights_path = os.getenv("FL_YOLO_WEIGHTS_PATH") or None
    weights_sha256 = os.getenv("FL_YOLO_WEIGHTS_SHA256") or None
    device = os.getenv("FL_YOLO_DEVICE", "cpu")
    epochs = int(os.getenv("FL_LOCAL_EPOCHS", "1"))
    image_size = int(os.getenv("FL_YOLO_IMAGE_SIZE", "320"))
    batch_size = int(os.getenv("FL_YOLO_BATCH_SIZE", "4"))
    num_rounds = int(os.getenv("FL_NUM_ROUNDS", "2"))

    # 1. Verify Dataset Partitioning
    partitions_base = Path("datasets/processed/partitions")
    if not (partitions_base / "client_0").exists():
        print("Partitioning VisDrone dataset for clients...")
        from datasets.tools.visdrone_prep.prepare import partition_dataset

        partition_dataset(
            images_dir="datasets/raw/visdrone/images",
            annotations_dir="datasets/raw/visdrone/annotations",
            output_dir=str(partitions_base),
            num_clients=3,
            samples_per_client=20,
        )

    client_configs = {}
    client_ids = ["client_0", "client_1", "client_2"]

    for cid in client_ids:
        train_img = partitions_base / cid / "train" / "images"
        train_ann = partitions_base / cid / "train" / "annotations"
        client_configs[cid] = ClientNodeConfig(
            client_id=cid,
            federation_id="fed_visdrone_drone_surveillance",
            dataset_config=DatasetConfig(
                images_dir=str(train_img),
                annotations_dir=str(train_ann),
                num_classes=10,
            ),
            training_config=TrainingConfig(
                model_name=model_name,
                weights_path=weights_path,
                weights_sha256=weights_sha256,
                epochs=epochs,
                batch_size=batch_size,
                image_size=image_size,
                device=device,
                learning_rate=0.01,
            ),
            model_version=f"mod_{model_name}_visdrone_v1",
        )

    # 2. Build ClientApp
    def client_fn(cid: str) -> TrustFLYOLOClient:
        return TrustFLYOLOClient(client_configs[cid])

    client_app = ClientApp(client_fn=client_fn)

    # 3. Build ServerApp with real YOLO initial parameters
    global_model = YOLOModelWrapper(
        model_name=model_name,
        num_classes=10,
        seed=42,
        device=device,
        weights_path=weights_path,
        weights_sha256=weights_sha256,
    )
    initial_params = global_model.get_parameters()

    server_app = create_server_app(
        num_rounds=num_rounds,
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=2,
        random_seed=42,
        initial_parameters=initial_params,
    )

    print(
        f"\nInitialized Global {model_name} model with {global_model.parameter_count():,} parameters "
        f"({len(initial_params)} tensors) on device={global_model.device}."
    )
    print(f"Executing {num_rounds} Federated Learning rounds with {len(client_ids)} clients...")

    # 4. Execute Federated Rounds
    evidence = []
    for r in range(1, num_rounds + 1):
        print(f"\n--- Starting Federated Round {r} ---")
        round_summary = server_app.fit_round(
            server_round=r,
            client_app=client_app,
            client_ids=client_ids,
        )
        fit_m = round_summary["fit_metrics"]
        eval_m = round_summary.get("eval_metrics", {})
        print(f"Round {r} Aggregation Complete:")
        print(f"  Successful Clients: {fit_m['num_successful_clients']}/{len(client_ids)}")
        print(f"  Total Images Processed: {fit_m['total_examples']}")
        print(f"  Validation Loss: {_fmt_metric(round_summary['loss'])}")
        print(f"  mAP50: {_fmt_metric(eval_m.get('map50'))}")
        print(f"  mAP50-95: {_fmt_metric(eval_m.get('map50_95'))}")
        print(f"  Precision: {_fmt_metric(eval_m.get('precision'))}")
        print(f"  Recall: {_fmt_metric(eval_m.get('recall'))}")
        evidence.append(round_summary)

    # 5. Measure Parameter Shift
    final_params = server_app.parameters
    total_delta = sum(
        sum(abs(f - i) for f, i in zip(layer_f, layer_i, strict=False))
        for layer_f, layer_i in zip(final_params, initial_params, strict=False)
    )
    print(f"\nTotal Global Parameter Update Magnitude (L1 norm): {total_delta:.6f}")

    # Save evidence
    out_file = Path("tests/output/yolo_fl_evidence.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_data = {
        "workload": f"Ultralytics {model_name} on VisDrone",
        "is_simulated": False,
        "rounds_executed": num_rounds,
        "clients": client_ids,
        "round_evidence": evidence,
        "parameter_l1_delta": round(total_delta, 6),
    }
    out_file.write_text(json.dumps(evidence_data, indent=2), encoding="utf-8")
    print(f"Evidence saved to: {out_file}")
    print("======================================================================")


if __name__ == "__main__":
    main()
