# TrustFL

**TrustFL** is a production-oriented Federated Learning research and development platform featuring:
- **Federated Coordination & Model Aggregation**
- **Immutable On-Chain Auditability** (Solidity contracts and the Web3 client)
- **Cryptographic Model Verification** (Ed25519 signatures and canonical SHA-256 artifacts)
- **Verifiable Artifact Storage** (local development storage or IPFS)
- **Zero-Knowledge Proofs (ZKP)** (a mandatory production verifier boundary for every coordinator update)
- **Extensible API Gateway & Real-Time Dashboard** (FastAPI & Next.js)

---

## 🏛 Repository Architecture

This repository is structured as a monorepo:

```
TrustFL/
├── apps/
│   ├── coordinator/       # Central FL orchestrator (round scheduling, aggregation trigger)
│   ├── client/            # Edge / participating FL worker runtime (local training & proof generation)
│   ├── api/               # FastAPI backend & external API gateway
│   └── dashboard/         # Next.js web console for audits, training rounds, and nodes
├── packages/
│   ├── schemas/           # Shared Pydantic data schemas & message protocols
│   ├── crypto/            # Cryptographic primitives (signing, key management, hashing)
│   ├── blockchain/        # EVM / contract interaction wrapper
│   └── storage/           # IPFS and local artifact storage adapters
├── packages/contracts/    # Solidity smart contracts for registry and round logs
├── packages/zkp/          # Circom commitment circuit and proof runtime
├── datasets/tools/        # Utilities for dataset partitioning, verification, and synthetic testing
├── infrastructure/        # Docker Compose, Kubernetes manifests, and cloud provisioning
├── tests/                 # Unit, integration, and end-to-end test suites
├── docs/                  # Architecture documentation and technical specifications
└── scripts/               # Developer automation, bootstrapping, and deployment scripts
```

For complete architectural details and security invariants, consult [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
For environment variable configuration, consult [docs/ENV_SETUP_GUIDE.md](docs/ENV_SETUP_GUIDE.md).
For Scenario 1 step-by-step execution on real VisDrone data, consult [docs/SCENARIO_1_WALKTHROUGH.md](docs/SCENARIO_1_WALKTHROUGH.md).
For multi-device and network deployment instructions (LAN/WAN/Localhost), consult [docs/DEPLOYMENT_SCENARIOS.md](docs/DEPLOYMENT_SCENARIOS.md).
For dashboard usage, consult [docs/DASHBOARD.md](docs/DASHBOARD.md). For operations
and production boundaries, consult [docs/OPERATIONS.md](docs/OPERATIONS.md) and
[DEPLOYMENT.md](DEPLOYMENT.md).

Compose credentials and services are development-only. Coordinator endpoints except
`/health` require an authenticated, registered client; production enrollment should
use per-client mTLS or identity-provider credentials.

---

## 🔒 Security & Privacy Policy: Zero-Git Principle

> **CRITICAL INVARIANT:**
> Under **NO** circumstances should private training data, cryptographic private keys, runtime secrets, or model checkpoint artifacts (`.pt`, `.pth`, `.bin`, `.safetensors`, `.onnx`, `.h5`, `.npy`, `.csv`, `.key`, `.pem`, etc.) ever be committed to Git.
>
> All training datasets remain local to the respective edge client or are partitioned synthetically via approved tooling. Model weights are stored exclusively in decentralized / object storage (e.g. IPFS/S3) referenced solely via cryptographic content identifiers (CIDs) and hashes recorded on-chain.

---

## 🚀 Getting Started

> **Single-host notice:** all client replicas in the default single-host topology share the
> same dataset directory. This demonstrates federated aggregation and
> cryptographic verification on a single machine; it does not demonstrate data
> privacy, data isolation, or statistical heterogeneity of independent data owners.
> See [DEPLOYMENT.md §5](DEPLOYMENT.md#5-single-host-notice).

### 1. Prerequisites

- **Docker**: `24+` with the Compose plugin (Docker Desktop 4.x ships both).
- *(Local development without Docker)*: **Python** `>= 3.11`, **Node.js** `>= 22.13`.

### 2. Quick Setup

```bash
# Clone the repository
git clone https://github.com/sayam-1705/trustfl.git
cd trustfl

# Copy example environment configuration
cp .env.example .env
```

### 3. Generate a Sample Dataset (Optional)

```bash
# Generate 60 synthetic images with random VisDrone-format annotations
python scripts/generate_sample_dataset.py --out-dir datasets/sample --num-images 60
```
Or point `FL_DATASET_DIR` in `.env` to your own VisDrone-format dataset.

### 4. Start the Stack

```bash
# Default: 2 federated clients
docker compose up --build

# Custom client count (e.g. 3 clients):
FL_NUM_CLIENTS=3 FL_MIN_CLIENTS=3 docker compose up --build
```

Services start in dependency order (`db` → `ipfs` → `hardhat` → `contract-deployer` → `api` → `client-init` → `coordinator` → `client` ×N).
The dashboard is accessible at http://localhost:3000 once services are healthy.

### 5. Published Images (Clean-machine deployment)

Pre-built images are published to GitHub Container Registry (GHCR). The
published stack is a strict production template: it requires pinned image
versions, real secrets, a deployed contract manifest, an external EVM RPC
endpoint, and a real dataset path. Use the regular `docker compose` stack for
the local Hardhat demo.

```bash
export TRUSTFL_VERSION=0.1.0
export POSTGRES_PASSWORD="$(openssl rand -hex 32)"
export API_READ_KEY="$(openssl rand -hex 32)"
export API_WRITE_KEY="$(openssl rand -hex 32)"
export API_ADMIN_KEY="$(openssl rand -hex 32)"
export DASHBOARD_ACCESS_KEY="$(openssl rand -hex 32)"
export COORDINATOR_ENROLLMENT_TOKEN="$(openssl rand -hex 32)"
export CORS_ALLOWED_ORIGINS=https://dashboard.example.com
export BLOCKCHAIN_RPC_URL=https://your-evm-rpc.example
export BLOCKCHAIN_CONTRACTS_DIR=/srv/trustfl/contracts
export COORDINATOR_PRIVATE_KEY=0x...
export FL_DATASET_DIR=/srv/trustfl/dataset
docker compose -f docker-compose.published.yml pull
docker compose -f docker-compose.published.yml up
```

`BLOCKCHAIN_CONTRACTS_DIR` must contain the deployed `contracts.json` manifest.
The published stack does not start Hardhat or deploy contracts automatically.

### 6. Monitor & Shutdown

```bash
# Check round status
curl -s -H "Authorization: Bearer trustfl-read-dev" \
  http://localhost:8000/rounds/federation/fed-default | python -m json.tool

# Graceful shutdown with volume cleanup
docker compose down --volumes
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full environment variable reference, architecture notes, and troubleshooting.

### Common Development Commands

| Command | Action |
| --- | --- |
| `make check` | Run Ruff, Python tests, and repository artifact/security checks |
| `make lint` | Run code quality checks (Ruff, ESLint) |
| `make format` | Automatically format codebases |
| `make test` | Execute unit and integration test suites |
| `make clean` | Remove temporary build, cache, and test artifacts |

The dashboard is read-only and uses a server-side API proxy so credentials are
never shipped to the browser. Signed updates and artifact hashes are mandatory
when `COORDINATOR_REQUIRE_SIGNATURES=true`; ZKP is independently tested but
mandatory in production; configure `ZKP_VERIFY_COMMAND` and a reviewed
`verification_key.json`/circuit artifact directory before starting the services.

### Client identity and enrollment

Production clients use durable Ed25519 identities. Registration creates a
`PENDING` enrollment; an administrator must approve it before the client can
heartbeat or submit updates. `SUSPENDED` and `REVOKED` identities are rejected,
public keys cannot be replaced in place, and key rotation returns the identity
to `PENDING`. Private keys stay client-side and must be provisioned through an
external secret manager (`CLIENT_KEY_STORE=kms` or `secret_manager`); they are
never sent to the API or stored in the database.

### Recovery and consistency

Round state and accepted update metadata are durable in the control-plane
database. The coordinator advances rounds through guarded validation,
aggregation, and commit states; duplicate client/round updates are rejected.
Blockchain audit work is recorded in a transactional outbox with stable
idempotency keys and bounded exponential retries, so an RPC outage leaves
operator-visible recovery work rather than losing the event. A queued or
submitted event must not be treated as final until the configured blockchain
confirmation policy has been satisfied.

---

## 📜 License

This project is licensed under the MIT License.
