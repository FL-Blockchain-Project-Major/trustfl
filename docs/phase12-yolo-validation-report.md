# Phase 12 — Real YOLO Federated Object Detection Validation Report

## 1. Environment & Hardware

- **CPU**: 12th Gen Intel Core i7-1255U (CPU-only; no NVIDIA CUDA GPU present)
- **OS**: Linux
- **Python**: 3.11.16
- **PyTorch**: `2.15.0+cpu`
- **Ultralytics**: `8.4.219`
- **Model**: `yolov8n` (`nc=10`, `3,023,198` floating-point `state_dict` parameters across `298` tensors)

## 2. Dataset & Configuration

- **Dataset**: VisDrone2019-DET-val (`datasets/raw/visdrone`), partitioned into 3 non-overlapping client directories (`datasets/processed/partitions/client_{0,1,2}`)
- **Training images per client**: 20 (`60` total per round across 3 clients)
- **Validation images per client**: 6
- **Configuration**:
  - `model_name`: `yolov8n` (initialized from `yolov8n.yaml` with `nc=10`)
  - `epochs`: `1` per round
  - `batch_size`: `4`
  - `image_size`: `320`
  - `learning_rate`: `0.01` (`AdamW`)
  - `device`: `cpu`
  - `rounds`: `2`

## 3. Reproducible Execution

```bash
PYTHONPATH=.:packages/fl_core:packages/ml_core:packages/crypto:packages/schemas \
  .venv/bin/python scripts/run_yolo_fl.py
```

Opt-in single-client VisDrone test:

```bash
.venv/bin/pytest tests/unit/ml/test_ml_core.py -k real_visdrone -v
```

## 4. Observed Results (`tests/output/yolo_fl_evidence.json`)

| Round | Successful Clients | Total Images Processed | Validation Loss | mAP50 | mAP50-95 | Precision | Recall |
|------:|-------------------:|-----------------------:|----------------:|------:|---------:|----------:|-------:|
| 1 | 3 / 3 | 60 | `null` (N/A) | `0.0000` | `0.0000` | `0.0000` | `0.0000` |
| 2 | 3 / 3 | 60 | `null` (N/A) | `0.0000` | `0.0000` | `0.0000` | `0.0000` |

- **Total Global Parameter Update Magnitude (L1 norm across 2 rounds)**: `22067.182607`
- **Notes**:
  - `Validation Loss` is `null` (`N/A`) because Ultralytics standalone `val()` reports box detection metrics (`mAP50`, `mAP50-95`, `precision`, `recall`) rather than validation loss, and TrustFL preserves `None` rather than substituting `0.0`.
  - `0.0000` mAP after 2 rounds of 1 epoch from scratch on 20 images/client at `imgsz=320` on CPU is expected for an un-pretrained YOLOv8n detector; higher resolution, pretrained weights (`FL_YOLO_WEIGHTS_PATH`), and GPU training are required for convergence.
