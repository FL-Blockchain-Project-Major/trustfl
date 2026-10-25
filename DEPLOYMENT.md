# TrustFL Deployment Guide

This document covers the full deployment workflow for TrustFL: from a clean
machine to a running federated-learning stack.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start (Development)](#2-quick-start-development)
3. [Configuring the Client Count](#3-configuring-the-client-count)
4. [Dataset Setup](#4-dataset-setup)
5. [Single-Host Notice](#5-single-host-notice)
6. [Published Images (Clean-machine install)](#6-published-images-clean-machine-install)
7. [Environment Variables Reference](#7-environment-variables-reference)
8. [Monitoring and Shutdown](#8-monitoring-and-shutdown)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

| Tool | Minimum version |
|------|-----------------|
| Docker | 24.x |
| Docker Compose plugin | v2.20 (ships with Docker Desktop 4.x) |
| `git` | any |

No Python, Node.js, or any other toolchain is required on the host machine.

---

## 2. Quick Start (Development)

```bash
# 1. Clone the repository
git clone https://github.com/sayam-1705/trustfl.git
cd trustfl

# 2. Copy and edit the environment file
cp .env.example .env
#    Set FL_DATASET_DIR, change secrets (see §7 for all variables)

# 3. (Optional) Generate a synthetic sample dataset for local testing
python scripts/generate_sample_dataset.py \
  --out-dir datasets/sample --num-images 60

# 4. Start the stack (builds images from source)
docker compose up --build

# 5. Check progress (open a second terminal)
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/rounds/federation/fed-default | python -m json.tool
```

The stack starts services in dependency order:
`db` → `ipfs` → `hardhat` → `contract-deployer` → `api` → `client-init` → `coordinator` → `client` (×N)

`client-init` generates persistent Ed25519 signing keys for every client slot
and writes `allowlist.json` before the coordinator or any client worker starts.

---

## 3. Configuring the Client Count

Set `FL_NUM_CLIENTS` to run any number of federated client workers.
The constraint `FL_MIN_CLIENTS ≤ FL_NUM_CLIENTS` is enforced at startup.

```bash
# Run 3 clients
FL_NUM_CLIENTS=3 FL_MIN_CLIENTS=3 docker compose up --build

# Run 1 client (single-client federation)
FL_NUM_CLIENTS=1 FL_MIN_CLIENTS=1 docker compose up --build

# Or set in .env:
#   FL_NUM_CLIENTS=3
#   FL_MIN_CLIENTS=3
```

**How it works:**

- `client-init` pre-provisions identities for `client_001` … `client_NNN` and
  writes `keys/allowlist.json`.
- The coordinator reads `allowlist.json` and accepts only pre-provisioned keys.
- Each `client` replica atomically claims a free slot via POSIX file locking on
  the shared `client_keys` Docker volume.
- Clients claim slots in order; if a slot is already held by another running
  replica it skips to the next.

**Error if misconfigured:**

```
Invalid quorum configuration: FL_MIN_CLIENTS (3) cannot exceed
FL_NUM_CLIENTS (2) in a single-host deployment.
```

---

## 4. Dataset Setup

### 4.1 Supported Directory Layouts

TrustFL auto-detects the following layouts inside `FL_DATASET_DIR`:

| Layout | Structure |
|--------|-----------|
| **Standard** | `<root>/train/images/` + `<root>/train/annotations/`<br>`<root>/val/images/` + `<root>/val/annotations/` *(optional)* |
| **Train/val** | `<root>/images/train/` + `<root>/annotations/train/` |
| **Flat** | `<root>/images/` + `<root>/annotations/` |

### 4.2 Annotation Format

VisDrone2019 text annotations — one `.txt` file per image, same base name:

```
<x>,<y>,<w>,<h>,<score>,<category>,<truncation>,<occlusion>
```

- Each field is an integer.
- `score=0` → ignored/invalid annotation (skipped during validation).
- Lines that do not parse as 8 comma-separated integers are skipped with a
  warning.

### 4.3 Using a Real Dataset

```bash
# Point to your VisDrone dataset (or any compatible dataset)
export FL_DATASET_DIR=/path/to/VisDrone2019-DET-train

docker compose up --build
```

### 4.4 Using the Sample Dataset

```bash
# Generate 60 synthetic images with random VisDrone annotations
python scripts/generate_sample_dataset.py \
  --out-dir datasets/sample --num-images 60

# datasets/sample is the default FL_DATASET_DIR
docker compose up --build
```

### 4.5 Pre-training Validation

Before the first training round begins each client:

1. Resolves the dataset layout.
2. Verifies image files are readable.
3. Counts valid annotation pairs (image + non-empty annotation file).
4. Exits non-zero with a clear error if validation fails.

Validation failures are surfaced immediately — not after a timeout:

```
ERROR Dataset validation failed on '/data/dataset': No usable samples found …
```

---

## 5. Single-Host Notice

> **This is a single-host protocol demonstration, not a privacy claim.**

When all client replicas run on the same machine and mount the same
`FL_DATASET_DIR`, they read identical data.  This configuration is useful for:

- Testing the federated aggregation and cryptographic verification protocols.
- Developing and debugging coordinator and client code.
- CI/CD pipeline validation.

It does **not** demonstrate:

- Data privacy between participants.
- Data isolation (each client truly owning separate data).
- Statistical heterogeneity (non-IID data across clients).

For a genuine federated deployment each client would run on a separate host
with its own private dataset.  See the [architecture documentation](docs/)
for multi-host deployment guidance.

---

## 6. Published Images (Clean-machine install)

Pre-built images are pushed to GHCR on every tagged release:

```bash
export TRUSTFL_VERSION=0.1.0

# Pull all images
docker compose -f docker-compose.published.yml pull

# Start the stack (no build required)
cp .env.example .env   # set FL_DATASET_DIR and secrets
docker compose -f docker-compose.published.yml up
```

Available images:

| Image | GHCR path |
|-------|-----------|
| API | `ghcr.io/sayam-1705/trustfl/api:<version>` |
| Coordinator | `ghcr.io/sayam-1705/trustfl/coordinator:<version>` |
| Client | `ghcr.io/sayam-1705/trustfl/client:<version>` |
| Dashboard | `ghcr.io/sayam-1705/trustfl/dashboard:<version>` |

---

## 7. Environment Variables Reference

### Federated Learning

| Variable | Default | Description |
|----------|---------|-------------|
| `FL_NUM_CLIENTS` | `2` | Number of client worker replicas to launch. |
| `FL_MIN_CLIENTS` | `2` | Minimum clients required before a round starts. Must be ≤ `FL_NUM_CLIENTS`. |
| `FL_NUM_ROUNDS` | `3` | Total number of federated rounds. |
| `FL_DATASET_DIR` | `./datasets/sample` | Host path to raw dataset; mounted read-only. |
| `FL_LOCAL_EPOCHS` | `1` | Local epochs per round per client. |
| `FL_MAX_SAMPLES` | `50` | Maximum training samples per client per round. |
| `FL_POLL_INTERVAL_SECONDS` | `3.0` | Client polling interval (seconds). |
| `FL_FEDERATION_ID` | `fed-default` | Federation identifier. |
| `FL_ROUND_TIMEOUT_SECONDS` | `60` | Seconds before a round times out. |
| `FL_HEARTBEAT_TIMEOUT_SECONDS` | `30` | Seconds before a client heartbeat expires. |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `COORDINATOR_ENROLLMENT_TOKEN` | — | Shared enrollment token (change in production). |
| `COORDINATOR_REQUIRE_SIGNATURES` | `true` | Enforce Ed25519 update signatures. |
| `COORDINATOR_INSECURE_DEV_AUTH` | `false` | **Never set in production.** Enables legacy shared-token enrollment. |
| `COORDINATOR_ENROLLMENT_ALLOWLIST_FILE` | — | Path to `allowlist.json` (written by `client-init`). |

### Database / Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `trustfl` | PostgreSQL user. |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (**change in production**). |
| `POSTGRES_DB` | `trustfl` | PostgreSQL database name. |
| `COORDINATOR_PRIVATE_KEY` | — | Coordinator blockchain signing key (**change in production**). |
| `API_READ_KEY` / `API_WRITE_KEY` / `API_ADMIN_KEY` | — | API auth keys (**change in production**). |

---

## 8. Monitoring and Shutdown

### Check Round Progress

```bash
# List all rounds for the default federation
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/rounds/federation/fed-default | python -m json.tool

# List client updates (shows which clients have submitted)
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/updates/federation/fed-default | python -m json.tool

# Check blockchain transactions (round finalization)
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  "http://localhost:8000/blockchain/transactions?limit=20" | python -m json.tool
```

### Follow Service Logs

```bash
docker compose logs -f coordinator
docker compose logs -f client
```

### Graceful Shutdown

```bash
# Stop all containers and remove volumes
docker compose down --volumes

# Stop containers but keep volumes (resume later)
docker compose stop
```

### Scaling Clients at Runtime

> **Not supported.** Change `FL_NUM_CLIENTS`, then `docker compose down --volumes && docker compose up --build`
> to re-provision identities and restart cleanly. Scaling without reprovisioning
> leaves the allowlist and quorum configuration inconsistent.

---

## 9. Troubleshooting

### `FL_MIN_CLIENTS > FL_NUM_CLIENTS`

```
Invalid quorum configuration: FL_MIN_CLIENTS (3) cannot exceed FL_NUM_CLIENTS (2)
```

**Fix:** Set `FL_MIN_CLIENTS` ≤ `FL_NUM_CLIENTS` in `.env`.

### Dataset validation fails

```
ERROR Dataset validation failed on '/data/dataset': No usable samples found
```

**Causes:**
- `FL_DATASET_DIR` does not exist on the host.
- Directory structure does not match any supported layout.
- No paired image + annotation files with valid annotations.

**Fix:**
1. Run `python scripts/generate_sample_dataset.py --out-dir datasets/sample` for a quick synthetic dataset.
2. Verify `FL_DATASET_DIR` matches the host path of your real dataset.

### All client slots occupied

```
RuntimeError: Unable to claim client identity: all N client identity slots in … are in use
```

**Cause:** More replicas are running than `FL_NUM_CLIENTS` slots were provisioned for. This happens after a failed partial cleanup.

**Fix:** `docker compose down --volumes && docker compose up --build`

### Coordinator never reaches quorum

```
Round 1 has been waiting for clients for 60s; aborting.
```

**Causes:**
- Clients exited early (check `docker compose logs client`).
- Dataset validation failed and clients exited nonzero.
- `FL_NUM_CLIENTS < FL_MIN_CLIENTS`.

### Dashboard not loading

The dashboard depends on the API. Verify the API is healthy:

```bash
curl http://localhost:8000/health/
```

### Blockchain transactions not confirmed

Check Hardhat logs:

```bash
docker compose logs hardhat
docker compose logs contract-deployer
```
