#!/usr/bin/env python3
"""
Executes a complete federated learning round on real VisDrone image & annotation data
using the modern Flower ServerApp/ClientApp and YOLO architecture.
"""

from __future__ import annotations
import json
from pathlib import Path
from apps.client.yolo_client import TrustFLYOLOClient
from apps.coordinator.coordinator import create_server_app
from trustfl_core.flower_app import ClientApp
from trustfl_ml.config import ClientNodeConfig, DatasetConfig, TrainingConfig
from trustfl_ml.yolo_wrapper import YOLOModelWrapper


def main() -> None:
    print("======================================================================")
    print("TrustFL Real Workload: Federated YOLO on VisDrone Dataset (Stage 03)")
    print("======================================================================")

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
            samples_per_client=30,
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
                model_name="yolov8n",
                epochs=2,
                batch_size=4,
                learning_rate=0.01,
            ),
            model_version="mod_yolov8n_visdrone_v1",
        )

    # 2. Build ClientApp
    def client_fn(cid: str) -> TrustFLYOLOClient:
        cfg = client_configs[cid]
        return TrustFLYOLOClient(cfg)

    client_app = ClientApp(client_fn=client_fn)

    # 3. Build ServerApp with YOLO model initial parameters
    global_model = YOLOModelWrapper(model_name="yolov8n", num_classes=10, seed=42)
    initial_params = global_model.get_parameters()

    server_app = create_server_app(
        num_rounds=2,
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=2,
        random_seed=42,
        initial_parameters=initial_params,
    )

    print(f"\nInitialized Global YOLO model with {len(initial_params[0]) + len(initial_params[1]) + len(initial_params[2])} parameters.")
    print(f"Executing Federated Learning rounds with {len(client_ids)} participating clients...")

    # 4. Execute Federated Rounds
    evidence = []
    for r in range(1, 3):
        print(f"\n--- Starting Federated Round {r} ---")
        round_summary = server_app.fit_round(
            server_round=r,
            client_app=client_app,
            client_ids=client_ids,
        )
        fit_m = round_summary["fit_metrics"]
        print(f"Round {r} Aggregation Complete:")
        print(f"  Successful Clients: {fit_m['num_successful_clients']}/{len(client_ids)}")
        print(f"  Total Images Processed: {fit_m['total_examples']}")
        print(f"  Validation Loss: {round_summary['loss']:.4f}")
        print(f"  mAP50 Accuracy Proxy: {round_summary['accuracy']:.2%}")
        evidence.append(round_summary)

    # 5. Measure Parameter Shift
    final_params = server_app.parameters
    total_delta = sum(
        sum(abs(f - i) for f, i in zip(layer_f, layer_i))
        for layer_f, layer_i in zip(final_params, initial_params)
    )
    print(f"\nTotal Global Parameter Update Magnitude (L1 norm): {total_delta:.6f}")

    # Save lightweight evidence
    out_file = Path("tests/output/yolo_fl_evidence.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_data = {
        "workload": "YOLO on VisDrone",
        "rounds_executed": 2,
        "clients": client_ids,
        "round_evidence": evidence,
        "parameter_l1_delta": round(total_delta, 6),
    }
    out_file.write_text(json.dumps(evidence_data, indent=2))
    print(f"Evidence saved to: {out_file}")
    print("======================================================================")


if __name__ == "__main__":
    main()
