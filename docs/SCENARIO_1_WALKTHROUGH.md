# TrustFL Scenario 1: Single-Device End-to-End Execution Guide
## Coordinator & Dual Edge Clients on Real VisDrone Dataset

This document provides a production-grade, reproducible walkthrough for orchestrating **Scenario 1** in TrustFL:
- **Topology**: Coordinator, 2 Client Nodes, EVM Hardhat Blockchain, IPFS Artifact Store, PostgreSQL Database, FastAPI API Gateway, and Next.js Dashboard running concurrently on the same physical host.
- **Workload**: Real drone imagery and bounding-box annotations from the **VisDrone 2019 DET Validation Dataset** (`VisDrone2019-DET-val`).
- **Execution Environments**: Automated containerized stack via Docker Compose and native host CLI option.

---

## Table of Contents
1. [Architecture & Topology Overview](#1-architecture--topology-overview)
2. [Prerequisites & System Preparation](#2-prerequisites--system-preparation)
3. [Environment Setup (.env)](#3-environment-setup-env)
4. [Dataset Partitioning (VisDrone)](#4-dataset-partitioning-visdrone)
5. [Docker Compose Stack Build & Configuration](#5-docker-compose-stack-build--configuration)
6. [Step-by-Step Execution Walkthrough](#6-step-by-step-execution-walkthrough)
7. [Comprehensive Feature Verification & Live Evidence](#7-comprehensive-feature-verification--live-evidence)
   - [7.1 Real VisDrone Dataset Training & Metric Convergence](#71-real-visdrone-dataset-training--metric-convergence)
   - [7.2 Cryptographic Client Identity & Ed25519 Signatures](#72-cryptographic-client-identity--ed25519-signatures)
   - [7.3 IPFS Model Weights Storage & SHA-256 Validation](#73-ipfs-model-weights-storage--sha-256-validation)
   - [7.4 Smart Contract On-Chain Auditing (EVM)](#74-smart-contract-on-chain-auditing-evm)
   - [7.5 Database Persistence & Alembic Migrations](#75-database-persistence--alembic-migrations)
   - [7.6 FastAPI Gateway & Role-Scoped Bearer Auth](#76-fastapi-gateway--role-scoped-bearer-auth)
   - [7.7 Next.js Control Room Dashboard](#77-nextjs-control-room-dashboard)
   - [7.8 Automated Test Suite Execution](#78-automated-test-suite-execution)
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
                                 ┌───────────────────────────┴───────────────────────────┐
                                 │                                                       │
                      ┌──────────┴───────────┐                                ┌──────────┴───────────┐
                      │    Client 001        │                                │    Client 002        │
                      │  (VisDrone Part. 1)  │                                │  (VisDrone Part. 2)  │
                      └──────────────────────┘                                └──────────────────────┘
```

### Communication Flow:
1. **Hardhat Blockchain** boots, deploys `ClientRegistry.sol`, `TrainingRoundRegistry.sol`, and `UpdateRegistry.sol`, and writes contract ABIs to a shared deployment volume.
2. **PostgreSQL** and **IPFS** boot and pass health checks.
3. **FastAPI Backend** performs database migrations (`alembic upgrade head`) and opens the REST API.
4. **Coordinator** registers with the smart contracts as `COORDINATOR_ROLE`, ensures federation initialization in PostgreSQL, and begins listening on port 8100.
5. **Client 1** and **Client 2** generate cryptographic Ed25519 keypairs, register with the coordinator with signed nonces, and start background polling loops.
6. When quorum (`FL_MIN_CLIENTS=2`) is reached, Round 1 starts:
   - Clients pull global model parameters.
   - Clients perform local training on their partitioned VisDrone images/labels.
   - Clients sign update payloads and submit weights + metrics.
   - Coordinator pins client weights to IPFS, validates signatures, verifies updates on-chain, executes FedAvg aggregation with weight clipping (`FL_MAX_CLIENT_WEIGHT_SHARE=0.5`), pins the aggregated model to IPFS, and finalizes the round on-chain.
7. Rounds repeat until `FL_NUM_ROUNDS=3` is reached, whereupon the coordinator gracefully finishes and clients stop.

---

## 2. Prerequisites & System Preparation

Verify system prerequisites:
- **Docker Engine**: `>= 24.0` with Docker Compose V2
- **Node.js**: `>= 20.x` & `npm`
- **Python**: `>= 3.11`
- **VisDrone Dataset**: Extracted at `/home/sayam/Desktop/project-data/VisDrone2019-DET-val`

Ensure images and annotations exist:
```bash
ls /home/sayam/Desktop/project-data/VisDrone2019-DET-val/VisDrone2019-DET-val/images | wc -l
# Expected: 548
ls /home/sayam/Desktop/project-data/VisDrone2019-DET-val/VisDrone2019-DET-val/annotations | wc -l
# Expected: 548
```

---

## 3. Environment Setup (.env)

Create or update `.env` in the repository root:

```bash
cp .env.example .env
```

Ensure `.env` contains the following configuration for Scenario 1:

```ini
# TrustFL Scenario 1 Environment Configuration

# ── Database ────────────────────────────────────────────────────────────────
POSTGRES_USER=trustfl
POSTGRES_PASSWORD=trustfl_dev_password_secure
POSTGRES_DB=trustfl
ENVIRONMENT=development
DATABASE_URL=postgresql://trustfl:trustfl_dev_password_secure@db:5432/trustfl

# ── Blockchain ───────────────────────────────────────────────────────────────
WEB3_PROVIDER_URI=http://127.0.0.1:8545
BLOCKCHAIN_RPC_URL=http://hardhat:8545
# Coordinator signing private key (Hardhat standard test account #0)
COORDINATOR_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
BLOCKCHAIN_ENABLED=true

# ── IPFS / Storage ───────────────────────────────────────────────────────────
IPFS_URL=http://ipfs:5001
IPFS_API_URL=http://ipfs:5001
STORAGE_BACKEND=ipfs

# ── Coordinator ──────────────────────────────────────────────────────────────
COORDINATOR_PORT=8100
COORDINATOR_HOST_PORT=8100
FL_MIN_CLIENTS=2
FL_NUM_ROUNDS=3
FL_ROUND_TIMEOUT_SECONDS=60
FL_HEARTBEAT_TIMEOUT_SECONDS=30
FL_MAX_CLIENT_WEIGHT_SHARE=0.5
FL_FINALIZE_MAX_RETRIES=5
FL_FINALIZE_RETRY_BASE_SECONDS=1

# ── API Gateway ──────────────────────────────────────────────────────────────
API_PORT=8000
API_SECRET_KEY=trustfl_api_secret_key_development_only
CORS_ALLOWED_ORIGINS=http://localhost:3000
API_AUTH_REQUIRED=true
API_READ_KEY=trustfl-read-dev-key
API_WRITE_KEY=trustfl-write-dev-key
API_ADMIN_KEY=trustfl-admin-dev-key
API_LEGACY_AUTH_COMPAT=false
API_RATE_LIMIT=100/minute
TRUSTED_PROXY_IPS=

# ── Next.js Dashboard ────────────────────────────────────────────────────────
HOSTNAME=0.0.0.0
PORT=3000
INTERNAL_API_URL=http://api:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_REFRESH_INTERVAL_SECONDS=15
DASHBOARD_ACCESS_KEY=trustfl-dashboard-dev
# Injected at build time into the browser bundle so the client-side Operations
# Console can include Authorization headers on /api/dashboard/* fetch calls.
NEXT_PUBLIC_API_READ_KEY=trustfl-read-dev-key
NEXT_PUBLIC_DASHBOARD_ACCESS_KEY=trustfl-dashboard-dev

# ── Client Identity & Enrollment ────────────────────────────────────────────
FL_FEDERATION_ID=fed-visdrone-local
COORDINATOR_REQUIRE_SIGNATURES=true
COORDINATOR_ENROLLMENT_TOKEN=trustfl-coordinator-dev-token
COORDINATOR_INSECURE_DEV_AUTH=true
STORAGE_LOCAL_DIR=/data/artifacts
IPFS_CONNECT_TIMEOUT_SECONDS=5
IPFS_READ_TIMEOUT_SECONDS=30

# ── VisDrone Dataset Configuration ──────────────────────────────────────────
VISDRONE_DATA_DIR=/home/sayam/Desktop/project-data/VisDrone2019-DET-val
VISDRONE_PARTITIONS_DIR=./datasets/processed/partitions
CLIENT_1_IMAGES_DIR=/data/partitions/client_001/train/images
CLIENT_1_ANNOTATIONS_DIR=/data/partitions/client_001/train/annotations
CLIENT_2_IMAGES_DIR=/data/partitions/client_002/train/images
CLIENT_2_ANNOTATIONS_DIR=/data/partitions/client_002/train/annotations
FL_LOCAL_EPOCHS=1
FL_MAX_SAMPLES=50
FL_POLL_INTERVAL_SECONDS=3.0
```

---

## 4. Dataset Partitioning (VisDrone)

To provide non-overlapping, realistic edge partitions to `client_001` and `client_002`, run the built-in partition tool:

```bash
PYTHONPATH=packages/ml_core python3 datasets/tools/visdrone_prep/prepare.py \
  --images /home/sayam/Desktop/project-data/VisDrone2019-DET-val/images \
  --annotations /home/sayam/Desktop/project-data/VisDrone2019-DET-val/annotations \
  --output datasets/processed/partitions \
  --clients 2 \
  --samples-per-client 50
```

Create compatibility symlinks for client IDs:
```bash
cd datasets/processed/partitions
ln -sf client_0 client_001
ln -sf client_1 client_002
cd ../../..
```

Verify that the partitions exist:
```bash
cat datasets/processed/partitions/dataset_manifest.json
```
Output:
```json
{
  "clients": {
    "client_0": {
      "train_samples": 40,
      "val_samples": 10,
      "train_images_dir": "datasets/processed/partitions/client_0/train/images",
      "train_annotations_dir": "datasets/processed/partitions/client_0/train/annotations",
      "val_images_dir": "datasets/processed/partitions/client_0/val/images",
      "val_annotations_dir": "datasets/processed/partitions/client_0/val/annotations"
    },
    "client_1": {
      "train_samples": 40,
      "val_samples": 10,
      "train_images_dir": "datasets/processed/partitions/client_1/train/images",
      "train_annotations_dir": "datasets/processed/partitions/client_1/train/annotations",
      "val_images_dir": "datasets/processed/partitions/client_1/val/images",
      "val_annotations_dir": "datasets/processed/partitions/client_1/val/annotations"
    }
  }
}
```

Audit Zero-Git invariant compliance:
```bash
make audit
# Expected: Audit passed: No sensitive data, weights or keys detected.
```

---

## 5. Docker Compose Stack Build & Configuration

Build all service container images:
```bash
docker compose build
```
This builds:
- `trustfl-api`
- `trustfl-coordinator`
- `trustfl-client-1`
- `trustfl-client-2`
- `trustfl-dashboard` (with `ENV HOSTNAME="0.0.0.0"` for clean container healthchecks)

---

## 6. Step-by-Step Execution Walkthrough

### Step 1: Launch Stack
```bash
docker compose up -d
```

### Step 2: Verify Service Health
```bash
docker compose ps
```
Expected output:
```text
NAME                          IMAGE                 STATUS                     PORTS
trustfl-api-1                 trustfl-api           Up (healthy)               127.0.0.1:8000->8000/tcp
trustfl-coordinator-1         trustfl-coordinator   Up (healthy)               127.0.0.1:8100->8100/tcp
trustfl-dashboard-1           trustfl-dashboard     Up (healthy)               127.0.0.1:3000->3000/tcp
trustfl-db-1                  postgres:15-alpine    Up (healthy)               127.0.0.1:5432->5432/tcp
trustfl-hardhat-1             node:22.13-alpine     Up (healthy)               127.0.0.1:8545->8545/tcp
trustfl-ipfs-1                ipfs/kubo:v0.32.1     Up (healthy)               127.0.0.1:8081->8080/tcp
trustfl-contract-deployer-1   node:22.13-alpine     Exited (0)                 
trustfl-client-1-1            trustfl-client-1      Up                         
trustfl-client-2-1            trustfl-client-2      Up                         
```

### Step 3: Monitor Live Training Progress
```bash
docker compose logs -f coordinator client-1 client-2
```

Live output illustrates:
1. `client_001` and `client_002` register with Ed25519 identity signatures.
2. Round 1 starts, clients train on VisDrone images/labels, and submit updates.
3. Coordinator verifies signatures, records on-chain transactions, aggregates weights, and writes artifacts to IPFS.
4. Rounds 2 and 3 complete with decreasing training loss.
5. Coordinator logs `Training complete. 3 rounds finished.` and cleanly exits with code 0.
6. Clients detect coordinator completion after poll retries and cleanly exit with code 0.

---

## 7. Comprehensive Feature Verification & Live Evidence

### 7.1 Real VisDrone Dataset Training & Metric Convergence
Query updates recorded in the database:
```bash
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" \
  http://localhost:8000/updates/federation/fed-visdrone-local | jq .data
```
Verified progression:
- **Round 1**:
  - `client_001`: `num_examples: 40`, `loss: 0.2203`
  - `client_002`: `num_examples: 40`, `loss: 0.2605`
- **Round 2**:
  - `client_001`: `num_examples: 40`, `loss: 0.2139` (improved)
  - `client_002`: `num_examples: 40`, `loss: 0.2544` (improved)
- **Round 3**:
  - `client_001`: `num_examples: 40`, `loss: 0.2077` (improved)
  - `client_002`: `num_examples: 40`, `loss: 0.2485` (improved)

### 7.2 Cryptographic Client Identity & Ed25519 Signatures
Query registered client public keys and registration challenge signatures:
```bash
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" \
  http://localhost:8000/clients/federation/fed-visdrone-local | jq .data
```
Returns authenticated Ed25519 public keys and signatures:
```json
[
  {
    "id": "client_001",
    "public_key_b64": "vluTvCs9wXjLZhPhzMqtVG7DwesQ0AykmcbPH5bgXI0=",
    "capabilities": {
      "registration_nonce": "cf6bd101e3204b53b1a3b673944fedbb",
      "registration_signature": "GCKp+UiNvOzepEZvT5WxzgIKRE9L4048HgOltMylugd0OC1Xp80CruLxPtRi+Mjj4yC6BLL+YbKR5S4zLZrCBQ=="
    }
  },
  {
    "id": "client_002",
    "public_key_b64": "W4HkE23+ILu00sdp+pQ+DMNfnqX0ODaPIkIPNAg3aO4=",
    "capabilities": {
      "registration_nonce": "23aef1bad8c44aed9a9cd6e5847f798d",
      "registration_signature": "WNONQU9aCfnp2QY50DFTd/aoxy4oFChcBHDe4QzHRuS3f+GBtR/tAxfWmoe9leN69kW27SoZa2hhy7msJq40Bw=="
    }
  }
]
```

### 7.3 IPFS Model Weights Storage & SHA-256 Validation
Check stored IPFS artifacts:
```bash
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" \
  http://localhost:8000/artifacts/federation/fed-visdrone-local | jq .data
```
Example Round 1 Global Model:
- **IPFS CID**: `QmarmBTEyaaMaD8LpiwvuM8brjWoGYJVMVewco6iRy5X86`
- **Recorded Hash**: `sha256:a10a1388730a27814440fe2aff7b5df6120fb7e9c9fcfc6fe22dc76f7b88f36f`

Verify directly against IPFS Kubo storage:
```bash
docker exec trustfl-ipfs-1 ipfs cat QmarmBTEyaaMaD8LpiwvuM8brjWoGYJVMVewco6iRy5X86 | sha256sum
# Output:
# a10a1388730a27814440fe2aff7b5df6120fb7e9c9fcfc6fe22dc76f7b88f36f  -
```
The computed SHA-256 hash matches the database and on-chain records exactly.

### 7.4 Smart Contract On-Chain Auditing (EVM)
Query the on-chain audit ledger:
```bash
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" \
  http://localhost:8000/blockchain/transactions | jq .data
```
Every key state transition is confirmed with a transaction receipt:
- `TrainingRoundRegistry.createRound` (Rounds 1, 2, 3)
- `TrainingRoundRegistry.activateRound` (Rounds 1, 2, 3)
- `UpdateRegistry.submitUpdate` (Updates from `client_001` and `client_002`)
- `UpdateRegistry.markVerificationState` (Marked `VERIFIED`)
- `UpdateRegistry.recordAggregation` (Aggregated into global model)
- `TrainingRoundRegistry.finalizeRound` (Rounds 1, 2, 3 finalized)

### 7.5 Database Persistence & Alembic Migrations
Verify rounds in PostgreSQL:
```bash
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" \
  http://localhost:8000/rounds/federation/fed-visdrone-local | jq .data
```
All rounds show `status: FINALIZED` with timestamps and IPFS artifact links.

### 7.6 FastAPI Gateway & Role-Scoped Bearer Auth
FastAPI enforces role-scoped authorization:
- `API_READ_KEY`: Authorized for `GET` requests (`/health/`, `/federations/`, `/rounds/`, `/clients/`, `/updates/`, `/artifacts/`, `/blockchain/transactions`).
- Unauthenticated requests return `401 Unauthorized`.
- Non-conforming payloads return `422 Unprocessable Entity`.

### 7.7 Next.js Control Room Dashboard

The Next.js dashboard is available at `http://localhost:3000`.

#### Architecture: Three-layer authorization

```
Browser (client-side)       Dashboard Container          FastAPI API
         │                          │                         │
         │  GET /api/dashboard/*    │                         │
         │  Sec-Fetch-Site:         │                         │
         │    same-origin           │                         │
         │─────────────────────────►│                         │
         │  (same-origin bypass)    │ GET /federations/ +     │
         │                          │ Authorization: Bearer   │
         │                          │ <API_READ_KEY>          │
         │                          │────────────────────────►│
         │                          │         200 OK          │
         │         200 OK           │◄────────────────────────│
         │◄─────────────────────────│                         │
```

**Layer 1 — Server-Side Pages** (`/security`, `/clients`, `/models`, `/rounds`):  
[`libs/api.ts`](../apps/dashboard/libs/api.ts) `fetchAPI()` uses `INTERNAL_API_URL=http://api:8000`
and injects `Authorization: Bearer <API_READ_KEY>` on every request.

**Layer 2 — Operations Console proxy** (`/api/dashboard/[...path]`):  
[`route.ts`](../apps/dashboard/app/api/dashboard/[...path]/route.ts) accepts browser requests that
arrive with `Sec-Fetch-Site: same-origin` without requiring an explicit bearer token.
All proxied calls to FastAPI unconditionally carry `Authorization: Bearer <API_READ_KEY>`.

**Layer 3 — External API access** (curl, integrations):  
External requests to `/api/dashboard/*` without a `Sec-Fetch-Site: same-origin` header
must supply `Authorization: Bearer <DASHBOARD_ACCESS_KEY>` or `<API_READ_KEY>`.

#### Verification commands

```bash
# Server-rendered pages (no auth required in browser — page handles server-side auth):
curl -s http://localhost:3000/security | grep -c "CONFIRMED"     # Blockchain TX count
curl -s http://localhost:3000/clients  | grep -c "client_00"     # Client rows
curl -s http://localhost:3000/rounds   | grep -c "FINALIZED"     # Finalized rounds
curl -s http://localhost:3000/models   | grep -c "ipfs://"       # Model artifacts

# Client-side proxy endpoints (external curl must supply dashboard bearer token):
curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  http://localhost:3000/api/dashboard/federations | jq .

curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  "http://localhost:3000/api/dashboard/rounds/federation/fed-visdrone-local" | jq .data

curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  "http://localhost:3000/api/dashboard/clients/federation/fed-visdrone-local" | jq .data

curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  "http://localhost:3000/api/dashboard/updates/federation/fed-visdrone-local" | jq .data

curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  "http://localhost:3000/api/dashboard/artifacts/federation/fed-visdrone-local" | jq .data

curl -sL -H "Authorization: Bearer trustfl-dashboard-dev" \
  "http://localhost:3000/api/dashboard/blockchain/transactions?limit=100" | jq .data

# All should return HTTP 200 with populated data arrays.
# Alternatively, API_READ_KEY also works as the bearer token.
```

### 7.8 Automated Test Suite Execution
Execute the automated test suites inside the container environment:

1. **Python Unit Tests** (87 tests):
```bash
docker run --rm -v $(pwd):/app -w /app \
  -e PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:. \
  trustfl-api:latest python -m unittest discover -s tests/unit -p "test_*.py"
# Result: Ran 87 tests in 2.009s — OK
```

2. **Python API & Integration Tests** (32 tests):
```bash
docker run --rm -u 0 -v $(pwd):/app -w /app \
  -e ENVIRONMENT=development \
  -e CORS_ALLOWED_ORIGINS=http://localhost:3000 \
  -e PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:. \
  trustfl-api:latest sh -c "pip install --no-cache-dir pytest pytest-asyncio >/dev/null && pytest tests/api tests/integration"
# Result: 32 passed in 20.81s
```

3. **Solidity Smart Contract Tests** (23 tests):
```bash
docker exec trustfl-hardhat-1 npx hardhat test
# Result: 23 passing (5s)
```

**Total**: 142 automated tests verified across smart contracts, cryptography, ML core, federated scheduling, and API security.

---

## 8. Troubleshooting & Diagnostic Guide

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `Dashboard container reports unhealthy` | Next.js standalone binds to `$HOSTNAME` (container ID) instead of `0.0.0.0`, causing loopback `127.0.0.1:3000` fetches to fail. | Add `ENV HOSTNAME="0.0.0.0"` in `apps/dashboard/Dockerfile` and `HOSTNAME=0.0.0.0` in `docker-compose.yml`. |
| `coordinator fails to start with contracts.json missing` | Hardhat node is still booting or contract-deployer has not finalized. | `docker-compose.yml` uses `depends_on: contract-deployer: condition: service_completed_successfully` to sequence deployment. |
| `Client training fallback to synthetic function` | `FL_IMAGES_DIR` or `FL_ANNOTATIONS_DIR` path is unset or directory is empty. | Verify volume mounts in `docker-compose.yml` pointing to `/data/partitions/client_001/train/images` and `annotations`. |
| `401 Unauthorized on FastAPI endpoints` | `API_AUTH_REQUIRED=true` and bearer token missing. | Include `-H "Authorization: Bearer <API_READ_KEY>"` on all HTTP queries. `API_READ_KEY=trustfl-read-dev-key` in `.env`. |
| `401 Unauthorized {"detail":"Dashboard authentication required"}` from `/api/dashboard/*` | External request arrived without `Sec-Fetch-Site: same-origin` header and no bearer token. | External curl scripts must include `-H "Authorization: Bearer trustfl-dashboard-dev"` (or `trustfl-read-dev-key`). Browser page-loads automatically qualify as same-origin. |
| `Dashboard server-side pages show no data (blank tables)` | `INTERNAL_API_URL` missing or `API_READ_KEY` not passed to dashboard container. | Ensure `docker-compose.yml` dashboard service has both `INTERNAL_API_URL=http://api:8000` and `API_READ_KEY=...` in its `environment:` block. Rebuild with `docker compose up -d --build dashboard`. |
| `Operations Console stuck on "Loading control-plane data…"` | Browser-side fetch to `/api/dashboard/federations` returning 401 or 308 redirect loop. | Ensure `NEXT_PUBLIC_API_READ_KEY` and `NEXT_PUBLIC_DASHBOARD_ACCESS_KEY` are set in `.env` and passed as `build.args` in `docker-compose.yml`. Rebuild dashboard image. |
| `RuntimeError: CORS_ALLOWED_ORIGINS must be configured in production` | `ENVIRONMENT=production` requires explicit origins without wildcards. | Ensure `CORS_ALLOWED_ORIGINS=http://localhost:3000` is set in `.env`. |
| `Zero-Git audit failure (make audit)` | Forbidden file extensions (`.pt`, `.pem`, `.csv`, `.npy`) committed to git. | Never add raw weights or partitions to git. Partitions under `datasets/processed/` are gitignored. |
| `Client exits with unreachable coordinator` | Normal behavior: Coordinator finishes `FL_NUM_ROUNDS` and shuts down; clients verify round completion and cleanly exit (0). | Check coordinator logs to confirm `Training complete. N rounds finished.` |

---

## 9. Quick Command Reference

```bash
# 1. Prepare dataset partitions
PYTHONPATH=packages/ml_core python3 datasets/tools/visdrone_prep/prepare.py \
  --images /home/sayam/Desktop/project-data/VisDrone2019-DET-val/images \
  --annotations /home/sayam/Desktop/project-data/VisDrone2019-DET-val/annotations \
  --output datasets/processed/partitions --clients 2 --samples-per-client 50

# 2. Build Docker images
docker compose build

# 3. Launch stack
docker compose up -d

# 4. View live logs
docker compose logs -f coordinator client-1 client-2

# 5. Check API status
curl -sL -H "Authorization: Bearer trustfl-read-dev-key" http://localhost:8000/rounds/federation/fed-visdrone-local | jq .

# 6. Stop stack and clean volumes
docker compose down -v
```

