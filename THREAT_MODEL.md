# TrustFL Threat Model & Security Audit

## 1. System Components
- **FastAPI Control Plane**: Orchestrates FL rounds, manages metadata.
- **Next.js Dashboard**: Read-only monitoring UI.
- **Smart Contracts**: EVM-based registries (Client, Round, Update).
- **IPFS Storage**: Decentralized model artifact blob storage.
- **Zero-Knowledge Prover (Circom)**: Off-chain verifiable computation constraints.

## 2. Mitigated Threats (Stage 12 Hardening)
1. **API Abuse & DoS (Oversized Payloads)**: Enforced via `RequestSizeLimitMiddleware` (1MB limit) and `slowapi` rate limits (100 req/min).
2. **Malformed Client Updates**: Enforced via strict `pydantic.Field` validation constraints (max lengths, bounded metrics).
3. **Replay Attacks (Updates)**: Re-submission of updates uses `nonce` checking in both the DB (`UpdateService`) and Smart Contract (`UpdateRegistry`).
4. **Duplicate Submissions**: Addressed in `UpdateService` to reject a second update from the same `client_id` in a given `round_id`.
5. **Contract Vulnerabilities**: Solved Slither findings (missing interface inheritance, missing `immutable` descriptors on registries).
6. **Denial of Service (Storage)**: Solved Bandit findings (B113) by adding `timeout=30` to external `requests` calls in the IPFS storage client to prevent hanging connections.
7. **Auditability**: Implemented `AuditLogMiddleware` for structured, JSON-based mutation logging, emitting an `X-Request-ID` and timing metrics.

## 3. Unresolved Security Issues (Accepted/Deferred Risks)
1. **Dependency Vulnerabilities (pip-audit)**: A full `pip-audit` scan revealed ~104 CVEs in base dependencies (e.g., `cryptography`, `urllib3`, `pillow`). We deferred a complete dependency resolution freeze/update to avoid breaking the local python environment compatibility.
2. **Authentication / Authorization (FastAPI)**: Currently, the REST API routes do not enforce JWT or token-based Authentication. Any network participant can hit the API.
3. **Private-Key Handling (Coordinator)**: Private keys for signing blockchain transactions are currently passed as raw environment variables / Hardhat defaults. Production requires a secure HSM or KMS integration (e.g., AWS KMS).
4. **Transport Layer Security (TLS)**: The FastAPI server relies on external TLS termination. Local host traffic is currently unencrypted HTTP.
5. **Round Timeouts & Client Crashes**: There is no active "reaper" worker running to prune or finalize rounds if participating clients drop offline mid-round, leading to indefinitely hanging rounds.
6. **Coordinator Crash Inconsistency**: If the coordinator crashes between saving state to the relational DB and submitting the transaction on-chain, the two state machines will diverge. A reliable outbox pattern or two-phase commit is needed.
7. **Database Failures**: SQLite is used for development. Production needs HA PostgreSQL with proper backups.
