# TrustFL Scenario 1: Single-Host End-to-End Execution Guide
## Coordinator & Single Edge Client on Real VisDrone Dataset

This document provides a production-grade, reproducible walkthrough for orchestrating **Scenario 1** in TrustFL:
- **Topology**: Coordinator, 1 Client Node, EVM Hardhat Blockchain, IPFS Kubo Artifact Store, PostgreSQL Database, FastAPI API Gateway, and Next.js Dashboard running concurrently on a single host.
- **Workload**: Real drone imagery and bounding-box annotations from the **VisDrone 2019 DET Validation Dataset** (`VisDrone2019-DET-val`).
- **Execution Environment**: Fully containerized stack managed via Docker Compose with dynamic client identity provisioning and slot claiming.

---

## Table of Contents
1. [Architecture & Topology Overview](#1-architecture--topology-overview)
2. [Prerequisites & Dataset Placement](#2-prerequisites--dataset-placement)
3. [Environment Configuration (.env)](#3-environment-configuration-env)
4. [Docker Compose Stack Build & Startup](#4-docker-compose-stack-build--startup)
5. [Step-by-Step Execution Walkthrough](#5-step-by-step-execution-walkthrough)
6. [Comprehensive Feature Verification & Live Evidence](#6-comprehensive-feature-verification--live-evidence)
   - [6.1 Real VisDrone Dataset Training & Metric Convergence](#61-real-visdrone-dataset-training--metric-convergence)
   - [6.2 Cryptographic Client Identity & Dynamic Slot Claiming](#62-cryptographic-client-identity--dynamic-slot-claiming)
   - [6.3 Smart Contract On-Chain Auditing (EVM)](#63-smart-contract-on-chain-auditing-evm)
   - [6.4 IPFS Model Weights Storage & SHA-256 Validation](#64-ipfs-model-weights-storage--sha-256-validation)
   - [6.5 FastAPI Gateway & Role-Scoped Bearer Auth](#65-fastapi-gateway--role-scoped-bearer-auth)
   - [6.6 Next.js Control Room Dashboard](#66-nextjs-control-room-dashboard)
7. [CI Pipeline: 3-Client Partitioning with Mock Data](#7-ci-pipeline-3-client-partitioning-with-mock-data)
8. [Troubleshooting & Diagnostic Guide](#8-troubleshooting--diagnostic-guide)

---

## 1. Architecture & Topology Overview

In Scenario 1, all TrustFL microservices communicate over an isolated Docker network (`trustfl_default` bridge):

```
                   ┌────────────────────────────────────────────────────────┐
                   │               TRUSTFL LOCAL STACK                      │
                   │                                                        │
                   │   ┌────────────────────┐      ┌────────────────────┐   │
                   │   │ Next.js Dashboard  │      │   FastAPI Gateway  │   │
                   │   │   (Port 3000)      │◄────►│    (Port 8000)     │   │
                   │   └────────────────────┘      └─────────┬──────────┘   │
                   │                                         │              │
                   │   ┌────────────────────┐      ┌─────────▼──────────┐   │
                   │   │  IPFS Kubo Node    │      │    Coordinator     │   │
                   │   │  (Port 5001/8081)  │◄────►│  (Port 8100/HTTP)  │   │
                   │   └────────────────────┘      └─────────▲──────────┘   │
                   │                                         │              │
                   │   ┌────────────────────┐                │              │
                   │   │ Hardhat EVM Node   │◄───────────────┤              │
                   │   │   (Port 8545)      │                │              │
                   │   └────────────────────┘                │              │
                   │                                         │              │
                   │   ┌────────────────────┐                │              │
                   │   │ PostgreSQL 15 DB   │◄───────────────┘              │
                   │   │   (Port 5432)      │                               │
                   │   └────────────────────┘                               │
                   └─────────────────────────────────────────┼──────────────┘
                                                             │
                                   UNIDIRECTIONAL POLLING    │
                                                 ┌───────────┴──────────┐
                                                 │      Client 001      │
                                                 │ (Real VisDrone Data) │
                                                 └──────────────────────┘
```

### Communication Flow:
1. **Infrastructure Initialization**:
   - `hardhat` boots EVM JSON-RPC at `8545`.
   - `contract-deployer` compiles and deploys `ClientRegistry.sol`, `TrainingRoundRegistry.sol`, and `UpdateRegistry.sol`, writing contract addresses and ABIs to the `contract_deployments` volume.
   - `db` (PostgreSQL 15) and `ipfs` (Kubo) boot and pass health checks.
2. **Client Identity Provisioning (`client-init`)**:
   - `client-init` executes `python -m trustfl_crypto.provision` on the shared `client_keys` volume.
   - Pre-provisions persistent Ed25519 signing keys for `client_001` and writes `allowlist.json`.
   - Exits with status `0` before the coordinator or client start.
3. **API & Coordinator Startup**:
   - `api` runs Alembic database migrations (`alembic upgrade head`) and serves the REST endpoints.
   - `coordinator` reads `allowlist.json` from `/var/lib/trustfl/keys:ro`, connects to the EVM contract deployer output, and starts listening on port 8100.
4. **Dynamic Client Worker Slot Claiming**:
   - `client` container launches with `FL_CLIENT_ID=auto`.
   - Acquires an exclusive file lock (`flock`) on `/var/lib/trustfl/keys/client_001/.lock`.
   - Loads the provisioned Ed25519 keypair and registers with the coordinator using a signed challenge nonce.
5. **Training & Finalization**:
   - Client validates the raw VisDrone dataset at `/data/dataset` (548 images, 548 annotations, 38,759 bounding boxes).
   - Once `FL_MIN_CLIENTS=1` quorum is registered, Round 1 starts.
   - Client trains simulated detector heads on the VisDrone samples, signs the parameter update, and submits it to the coordinator.
   - Coordinator verifies the Ed25519 signature, commits transactions on-chain (`submitUpdate`, `markVerificationState`), computes FedAvg aggregation with weight clipping (`FL_MAX_CLIENT_WEIGHT_SHARE=1.0`), pins the aggregated model to IPFS, and finalizes the round on-chain (`finalizeRound`).
   - Coordinator exits cleanly (`exit 0`). Client detects coordinator completion and stops gracefully.

---

## 2. Prerequisites & Dataset Placement

### 2.1 System Requirements
- **Docker Engine**: `>= 24.0` with Docker Compose V2 plugin.
- **Python**: `>= 3.11` (for running local scripts/tools).
- **RAM**: Minimum 8 GB recommended for concurrent Compose services.

### 2.2 Dataset Location & Verification
The real VisDrone dataset is copied from `/home/sayam/Desktop/project-data/VisDrone2019-DET-val/VisDrone2019-DET-val` into the designated project location: `datasets/raw/VisDrone2019-DET-val`.

```bash
# 1. Create target directory and copy real VisDrone data
mkdir -p datasets/raw
cp -r /home/sayam/Desktop/project-data/VisDrone2019-DET-val/VisDrone2019-DET-val datasets/raw/

# 2. Verify dataset files in project location
ls datasets/raw/VisDrone2019-DET-val/images | wc -l
# Output: 548 (.jpg images)

ls datasets/raw/VisDrone2019-DET-val/annotations | wc -l
# Output: 548 (.txt annotations)
```

Validate dataset layout and annotations with the Python resolver (using local virtualenv or Docker):
```bash
# Option A: Using local python
PYTHONPATH=packages/ml_core python3 -c "
from trustfl_ml.dataset import resolve_and_validate_dataset
info = resolve_and_validate_dataset('datasets/raw/VisDrone2019-DET-val')
print('Valid pairs:', info['stats']['valid_pairs'])
print('Total boxes:', info['stats']['total_boxes'])
"

# Option B: Using the built trustfl-client container (no host python dependencies needed)
docker run --rm -v $(pwd)/datasets/raw/VisDrone2019-DET-val:/data/dataset:ro trustfl-client python -c "
from trustfl_ml.dataset import resolve_and_validate_dataset
info = resolve_and_validate_dataset('/data/dataset')
print('Valid pairs:', info['stats']['valid_pairs'])
print('Total boxes:', info['stats']['total_boxes'])
"
```
**Output:**
```
Valid pairs: 548
Total boxes: 38759
```

> **Single-Host Protocol Demonstration Notice**:
> In this single-host configuration, the dataset directory is mounted read-only into `/data/dataset:ro`. This topology exercises federated aggregation, cryptographic verification, IPFS storage, and blockchain consensus; it is a protocol demonstration on a single machine and does not represent physical edge data privacy.

---

## 3. Environment Configuration (.env)

Create or update `.env` in the repository root for Scenario 1:

```ini
# TrustFL Scenario 1 Configuration (1 Client, Real VisDrone Dataset)

# ── Database ────────────────────────────────────────────────────────────────
POSTGRES_USER=trustfl
POSTGRES_PASSWORD=trustfl
POSTGRES_DB=trustfl
ENVIRONMENT=development
DATABASE_URL=postgresql://trustfl:trustfl@db:5432/trustfl

# ── Blockchain ───────────────────────────────────────────────────────────────
WEB3_PROVIDER_URI=http://127.0.0.1:8545
BLOCKCHAIN_RPC_URL=http://hardhat:8545
COORDINATOR_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
BLOCKCHAIN_ENABLED=true

# ── IPFS / Storage ───────────────────────────────────────────────────────────
IPFS_URL=http://ipfs:5001
IPFS_API_URL=http://ipfs:5001
STORAGE_BACKEND=ipfs

# ── Coordinator ──────────────────────────────────────────────────────────────
COORDINATOR_PORT=8100
COORDINATOR_HOST_PORT=8100
FL_FEDERATION_ID=fed-visdrone-local
FL_NUM_CLIENTS=1
FL_MIN_CLIENTS=1
FL_NUM_ROUNDS=1
FL_ROUND_TIMEOUT_SECONDS=60
FL_HEARTBEAT_TIMEOUT_SECONDS=30
FL_MAX_CLIENT_WEIGHT_SHARE=1.0
FL_FINALIZE_MAX_RETRIES=5
FL_FINALIZE_RETRY_BASE_SECONDS=1
COORDINATOR_REQUIRE_SIGNATURES=true
COORDINATOR_ENROLLMENT_TOKEN=trustfl-coordinator-dev
COORDINATOR_INSECURE_DEV_AUTH=true
COORDINATOR_ENROLLMENT_ALLOWLIST_FILE=/var/lib/trustfl/keys/allowlist.json

# ── Dataset & Client ────────────────────────────────────────────────────────
FL_DATASET_DIR=./datasets/raw/VisDrone2019-DET-val
FL_CLIENT_ID=auto
FL_LOCAL_EPOCHS=1
FL_MAX_SAMPLES=20
FL_POLL_INTERVAL_SECONDS=3.0

# ── API Gateway ──────────────────────────────────────────────────────────────
API_PORT=8000
API_AUTH_REQUIRED=true
API_READ_KEY=trustfl-read-dev
API_WRITE_KEY=trustfl-write-dev
API_ADMIN_KEY=trustfl-admin-dev
CORS_ALLOWED_ORIGINS=http://localhost:3000

# ── Dashboard ────────────────────────────────────────────────────────────────
HOSTNAME=0.0.0.0
PORT=3000
INTERNAL_API_URL=http://api:8000
DASHBOARD_ACCESS_KEY=trustfl-dashboard-dev
NEXT_PUBLIC_API_READ_KEY=trustfl-read-dev
NEXT_PUBLIC_DASHBOARD_ACCESS_KEY=trustfl-dashboard-dev
```

---

## 4. Docker Compose Stack Build & Startup

### Step 1: Build Images
Build the container images from source:
```bash
docker compose build
```
This builds:
- `trustfl-api`: FastAPI gateway with database migrations and blockchain services.
- `trustfl-coordinator`: Orchestrator managing round lifecycles, Ed25519 verification, IPFS pinning, and EVM contract transactions.
- `trustfl-client`: Worker container (used both for `client-init` provisioning and `client` runtime).
- `trustfl-dashboard`: Next.js control room dashboard.

### Step 2: Launch Stack
```bash
docker compose up -d
```

### Step 3: Verify Service Health
```bash
# Check running service states (or use `docker compose ps -a` to view all including exited)
docker compose ps -a
```
**Observed Container States:**
```text
NAME                          IMAGE                 COMMAND                  SERVICE             STATUS                    PORTS
trustfl-api-1                 trustfl-api           "sh -c 'alembic -c a…"   api                 Up (healthy)              127.0.0.1:8000->8000/tcp
trustfl-dashboard-1           trustfl-dashboard     "docker-entrypoint.s…"   dashboard           Up (healthy)              127.0.0.1:3000->3000/tcp
trustfl-db-1                  postgres:15-alpine    "docker-entrypoint.s…"   db                  Up (healthy)              127.0.0.1:5432->5432/tcp
trustfl-hardhat-1             node:22.13-alpine     "docker-entrypoint.s…"   hardhat             Up (healthy)              127.0.0.1:8545->8545/tcp
trustfl-ipfs-1                ipfs/kubo:v0.32.1     "/sbin/tini -- /usr/…"   ipfs                Up (healthy)              127.0.0.1:8081->8080/tcp
trustfl-contract-deployer-1   node:22.13-alpine     "docker-entrypoint.s…"   contract-deployer   Exited (0)
trustfl-client-init-1         trustfl-client        "python -m trustfl_c…"   client-init         Exited (0)
trustfl-coordinator-1         trustfl-coordinator  "python apps/coordin…"   coordinator         Exited (0)
trustfl-client-1              trustfl-client        "python apps/client/…"   client              Exited (0)
```
*(Note: During training, `coordinator` and `client` are `Up`; once Round 1 completes, both transition to `Exited (0)` cleanly).*

---

## 5. Step-by-Step Execution Walkthrough

### 1. `client-init` Identity Provisioning
```bash
docker compose logs client-init
```
**Actual Output:**
```
INFO  Provisioned 1 persistent client identities in /var/lib/trustfl/keys; wrote allowlist to /var/lib/trustfl/keys/allowlist.json
Successfully provisioned 1 client identities:
  client_001: bBb4BefyWuJIyafZOBFcPuHB5C0N2/yJ56kpa9Q0I0A=
```

### 2. `client` Dynamic Slot Claiming & Real VisDrone Training
```bash
docker compose logs client
```
**Actual Output:**
```
INFO  client.main | No static FL_CLIENT_ID provided; claiming dynamic slot from 1 available in /var/lib/trustfl/keys...
INFO  trustfl.crypto.provision | Worker successfully claimed identity client_001 (lock held on /var/lib/trustfl/keys/client_001/.lock)
INFO  client.main | Using client identity client_001 (public key: bBb4BefyWuJIyafZOBFcPuHB5C0N2/yJ56kpa9Q0I0A=)
INFO  client.main | Resolving and validating raw dataset root: /data/dataset
INFO  client.main | Dataset validated successfully: 548 usable samples, 38759 total boxes from /data/dataset/images
INFO  client.main | NOTE: Single-host protocol demonstration: Client client_001 is reading shared dataset at '/data/dataset'.
INFO  client.main | Using simulated detector training function on dataset: /data/dataset/images
INFO  network.agent | [client_001] Registered with coordinator.
INFO  client.main | Client client_001 connected and registered with http://coordinator:8100
INFO  network.agent | [client_001] Coordinator has been unreachable for 5 consecutive polls after submitting round 1 — assuming federation complete, exiting.
INFO  client.main | Client client_001 stopped.
```

### 3. `coordinator` Federation Lifecycle & Blockchain Finalization
```bash
docker compose logs coordinator
```
**Actual Output:**
```
INFO  network.server | Restored coordinator state at round 0 (0 clients)
INFO  network.server | CoordinatorServer started on 0.0.0.0:8100
INFO  coordinator.main | Coordinator running: 0.0.0.0:8100  min_clients=1  num_rounds=1
INFO  packages.blockchain.trustfl_blockchain.client | Registering client client_001 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx 6dcf26e0cf9f995172e27b76c623fc06dd489f51517d9c4de6632ea93fed8854 (ClientRegistry.registerClient)
INFO  network.server | Round 1 started with 1 clients
INFO  network.server | Client registered: client_001
INFO  packages.blockchain.trustfl_blockchain.client | Creating round 1 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx d56162b4689eaa7fd97fdb5d881a1bc5b83792ba077d052ae6100be2ebe9d52a (TrainingRoundRegistry.createRound)
INFO  packages.blockchain.trustfl_blockchain.client | Activating round 1 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx d029805901d7f96203f89756be8cfb154c951226d54e3aa2c281a17d029b6246 (TrainingRoundRegistry.activateRound)
INFO  packages.blockchain.trustfl_blockchain.client | Submitting update update_client_001_1 from client_001 for round 1 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx 623342e6dac76e72c4a74fd769b619ebc78d363460474fcdee763b97150244aa (UpdateRegistry.submitUpdate)
INFO  packages.blockchain.trustfl_blockchain.client | Marking update update_client_001_1 as Verified on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx 661173762dd3e1c83c4da08ce80567300a7c9e794c9e49947fc6d955e68e4df0 (UpdateRegistry.markVerificationState)
INFO  packages.blockchain.trustfl_blockchain.client | Recording aggregation for update update_client_001_1 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx b5277d9729e5592b326186195e7372ef4599a05a66ab1bbf95c1450837af3285 (UpdateRegistry.recordAggregation)
INFO  packages.blockchain.trustfl_blockchain.client | Finalizing round 1 on-chain...
INFO  apps.api.api.services.blockchain_service | Recording blockchain tx 5467fbaaef637f58d9f16cabf1cd94fc5b924624aacd2a3aa08c69e48abc5dc1 (TrainingRoundRegistry.finalizeRound)
INFO  network.server | CoordinatorServer stopped.
INFO  coordinator.main | Training complete. 1 rounds finished.
```

---

## 6. Comprehensive Feature Verification & Live Evidence

### 6.1 Real VisDrone Dataset Training & Metric Convergence
Query recorded training updates:
```bash
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/updates/federation/fed-visdrone-local | python3 -m json.tool
```
**Output:**
```json
{
  "success": true,
  "data": [
    {
      "id": "update_client_001_1",
      "round_id": "fed-visdrone-local_round1",
      "client_id": "client_001",
      "status": "AGGREGATED",
      "artifact_id": "update_client_001_1",
      "artifact_hash": "sha256:0dc4fd4786e6c55ea1c7dbcba343bc54b7d68e01217e6cfe3ac9d1346964399a",
      "nonce": "client_001:1:7ec9cf5fea84ac48baa1910b5764fc38",
      "num_examples": 20,
      "loss": 0.2245,
      "submitted_at": "2026-10-26T13:19:29.908127Z",
      "verified_at": "2026-10-26T13:19:29.890936Z"
    }
  ],
  "message": "OK"
}
```

### 6.2 Cryptographic Client Identity & Dynamic Slot Claiming
Query the registered client identity:
```bash
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/clients/federation/fed-visdrone-local | python3 -m json.tool
```
**Output:**
```json
{
  "success": true,
  "data": [
    {
      "id": "client_001",
      "federation_id": "fed-visdrone-local",
      "public_key_b64": "uAC0+xi3eMFnlYTZhQW2DP6lFgOFheUUdO67QlzC38M=",
      "is_active": true,
      "capabilities": {
        "public_key": "uAC0+xi3eMFnlYTZhQW2DP6lFgOFheUUdO67QlzC38M=",
        "registration_nonce": "512b05fc9ede4ad6972a8d0a0b8bad13",
        "registration_signature": "V+yy/YJq5x2MfaIWh3GThPA2pKqB7IeTrm6kKm4PpM/6X07SrlU53NpkLPTWBB6Jqv/+WfNR6itj0OC26e5CCQ=="
      },
      "registered_at": "2026-10-26T13:19:29.220656Z",
      "last_seen_at": "2026-10-26T13:19:29.217265Z"
    }
  ],
  "message": "OK"
}
```

### 6.3 Smart Contract On-Chain Auditing (EVM)
Query confirmed blockchain transactions:
```bash
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  "http://localhost:8000/blockchain/transactions?limit=10" | python3 -m json.tool
```
**Output Summary (7 Confirmed Transactions):**
1. `ClientRegistry.registerClient` — `CONFIRMED`
2. `TrainingRoundRegistry.createRound` — `CONFIRMED`
3. `TrainingRoundRegistry.activateRound` — `CONFIRMED`
4. `UpdateRegistry.submitUpdate` — `CONFIRMED`
5. `UpdateRegistry.markVerificationState` — `CONFIRMED`
6. `UpdateRegistry.recordAggregation` — `CONFIRMED`
7. `TrainingRoundRegistry.finalizeRound` — `CONFIRMED`

### 6.4 IPFS Model Weights Storage & SHA-256 Validation
Query artifacts recorded in the database:
```bash
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/artifacts/federation/fed-visdrone-local | python3 -m json.tool
```
The aggregated model is stored with an IPFS CID (`ipfs://QmeTDaXjMpPZtU4zwY8iT3ZiMQWW7XhiW72ENhkopEU55Q`) and verified with its canonical SHA-256 digest (`sha256:a14e062e1d97046acd3e7816b9cae104c98f31c715c0d2bd851b10958d1282a3`).

### 6.5 FastAPI Gateway & Role-Scoped Bearer Auth
- `GET http://localhost:8000/federations/` with valid `API_READ_KEY` returns `200 OK`.
- Unauthenticated requests return `401 Unauthorized`:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/federations/
# Output: 401
```

### 6.6 Next.js Control Room Dashboard
Query the Next.js API proxy:
```bash
curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  http://localhost:3000/api/dashboard/federations | python3 -m json.tool
```
**Output:**
```json
{
  "success": true,
  "data": [
    {
      "id": "fed-visdrone-local",
      "name": "TrustFL Federation",
      "description": null,
      "status": "ACTIVE",
      "min_clients": 1,
      "max_rounds": 1,
      "created_at": "2026-10-26T13:19:25.108775Z",
      "updated_at": "2026-10-26T13:19:25.108785Z"
    }
  ],
  "message": "OK"
}
```

---

## 7. CI Pipeline: 3-Client Partitioning with Mock Data

For the continuous integration pipeline (`.github/workflows/ci.yml`), TrustFL tests multi-client federated learning using synthetic data:

### 7.1 Dataset Generation & Round-Robin Partitioning
1. `scripts/generate_sample_dataset.py --out-dir ./datasets/sample --train-samples 30` creates 30 synthetic images with VisDrone-format annotations.
2. In `SimulatedDetector.train_on_dataset` (`packages/ml_core/trustfl_ml/yolo_wrapper.py`), images are partitioned round-robin:
   ```python
   if num_clients > 1:
       eff_idx = client_index % num_clients
       image_files = [f for i, f in enumerate(all_image_files) if i % num_clients == eff_idx][
           :max_samples
       ]
   else:
       image_files = all_image_files[:max_samples]
   ```
3. With 30 images and 3 clients:
   - `client_001` (index 0) trains on 10 images (indices 0, 3, 6, 9, 12, 15, 18, 21, 24, 27).
   - `client_002` (index 1) trains on 10 images (indices 1, 4, 7, 10, 13, 16, 19, 22, 25, 28).
   - `client_003` (index 2) trains on 10 images (indices 2, 5, 8, 11, 14, 17, 20, 23, 26, 29).

### 7.2 Full E2E Verification in CI
The CI test verifies:
- `FL_NUM_CLIENTS=3` and `FL_MIN_CLIENTS=3`.
- `client-init` provisions keys for all 3 clients.
- All 3 clients register and submit verified updates across 3 rounds.
- All 3 rounds reach `FINALIZED` status with confirmed on-chain EVM transactions.

---

## 8. Troubleshooting & Diagnostic Guide

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'trustfl_crypto'` in `client-init` | Container `PYTHONPATH` missing `/app/packages/crypto`. | Resolved in `apps/client/Dockerfile` by defining `PYTHONPATH=/app/packages/crypto:/app/packages/ml_core:...`. |
| `FL_MAX_CLIENT_WEIGHT_SHARE` clipping single client | With 1 client, default clipping `0.5` causes incomplete aggregation. | Set `FL_MAX_CLIENT_WEIGHT_SHARE=1.0` in `.env` when `FL_NUM_CLIENTS=1`. |
| `Unable to claim client identity: all N slots in use` | Stale lock files from previous unclean termination. | Run `docker compose down -v` to reset container volumes. |
| Dashboard 308 redirect on `/api/dashboard/federations/` | Trailing slash triggers Next.js canonical redirect. | Use `/api/dashboard/federations` without trailing slash or `curl -L`. |
| Dataset validation failure | Directory missing images or annotations. | Ensure `FL_DATASET_DIR` points to a directory with `images/` and `annotations/` subdirectories. |

---

## 9. Teardown
To reset the environment and clean up all volumes:
```bash
docker compose down -v
```
