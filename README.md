# TrustFL

**TrustFL** is a production-oriented Federated Learning research and development platform featuring:
- **Federated Coordination & Model Aggregation**
- **Immutable On-Chain Auditability** (Solidity contracts and the Web3 client)
- **Cryptographic Model Verification** (Ed25519 signatures and canonical SHA-256 artifacts)
- **Verifiable Artifact Storage** (local development storage or IPFS)
- **Zero-Knowledge Proofs (ZKP)** (an independently implemented and tested optional verifier boundary; coordinator updates currently require signatures and artifact hashes)
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
For dashboard usage, consult [docs/DASHBOARD.md](docs/DASHBOARD.md). For operations
and production boundaries, consult [docs/OPERATIONS.md](docs/OPERATIONS.md) and
[DEPLOYMENT.md](DEPLOYMENT.md).

---

## 🔒 Security & Privacy Policy: Zero-Git Principle

> **CRITICAL INVARIANT:**
> Under **NO** circumstances should private training data, cryptographic private keys, runtime secrets, or model checkpoint artifacts (`.pt`, `.pth`, `.bin`, `.safetensors`, `.onnx`, `.h5`, `.npy`, `.csv`, `.key`, `.pem`, etc.) ever be committed to Git.
>
> All training datasets remain local to the respective edge client or are partitioned synthetically via approved tooling. Model weights are stored exclusively in decentralized / object storage (e.g. IPFS/S3) referenced solely via cryptographic content identifiers (CIDs) and hashes recorded on-chain.

---

## 🚀 Getting Started

### Prerequisites

- **Python**: `>= 3.11` (managed via `uv` or standard venv)
- **Node.js**: `>= 22.13` & `npm`
- **Make**: Standard build automation utility

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/sayam-1705/trustfl.git
cd TrustFL

# Copy example environment configuration
cp .env.example .env

# Verify environment and tooling
make check
```

### Common Commands

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
optional/deferred in the coordinator lifecycle.

---

## 📜 License

This project is licensed under the MIT License.
