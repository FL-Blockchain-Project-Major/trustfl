# TrustFL Threat Model & Security Audit

## 1. System Components
- **FastAPI Control Plane**: Orchestrates FL rounds, manages metadata.
- **Next.js Dashboard**: Read-only monitoring UI.
- **Smart Contracts**: EVM-based registries (Client, Round, Update).
- **IPFS Storage**: Decentralized model artifact blob storage.
- **Zero-Knowledge Prover (Circom)**: Off-chain verifiable computation constraints.

## 2. Mitigated Threats (Current hardening)
1. **API Abuse & DoS (Oversized Payloads)**: Enforced via `RequestSizeLimitMiddleware` (1MB limit), the coordinator HTTP limit, and an explicit global fixed-window rate limit (100 req/min).
2. **Malformed Client Updates**: Enforced via strict `pydantic.Field` validation constraints (max lengths, bounded metrics).
3. **Replay Attacks (Updates)**: Re-submission of updates uses `nonce` checking in both the DB (`UpdateService`) and Smart Contract (`UpdateRegistry`).
4. **Duplicate Submissions**: Addressed in `UpdateService` to reject a second update from the same `client_id` in a given `round_id`.
5. **Contract Vulnerabilities**: Solved Slither findings (missing interface inheritance, missing `immutable` descriptors on registries).
6. **Denial of Service (Storage)**: IPFS add/cat operations use explicit connect/read timeouts to prevent hanging connections.
7. **Auditability**: Implemented `AuditLogMiddleware` for structured, JSON-based mutation logging, emitting an `X-Request-ID` and timing metrics.

## 3. Unresolved Security Issues (Accepted/Deferred Risks)
1. **Dependency Vulnerabilities**: Dependency advisories must be scanned and triaged as part of release management. The repository does not claim that a local dependency installation is a complete vulnerability assessment.
2. **Authentication / Authorization (FastAPI)**: Production uses separate role-scoped bearer keys (`API_READ_KEY`, `API_WRITE_KEY`, and `API_ADMIN_KEY`) for read, mutation, and destructive requests. This is scoped shared-secret authorization, not a user/session identity provider.
3. **Private-Key Handling (Coordinator)**: Local Compose uses a Hardhat development key only. Production requires a secure HSM or KMS integration and must not use the Compose default.
4. **Transport Layer Security (TLS)**: The FastAPI server relies on external TLS termination. Local host traffic is currently unencrypted HTTP. Production ingress must redirect HTTP to HTTPS and set HSTS only after TLS is verified.
5. **Round Timeouts & Client Crashes**: The coordinator monitor marks stale clients offline and finalizes timed-out rounds. Operators still need to size timeouts for their deployment and monitor failed rounds.
6. **Coordinator Crash Inconsistency**: Lifecycle metadata is persisted through the API database adapter, but blockchain submission is not atomically coupled to the database. A durable outbox/reconciliation worker is still needed.
7. **Database Failures**: SQLite is supported for development. Production needs HA PostgreSQL with proper backups.
8. **ZKP enforcement**: The Circom implementation in `packages/zkp/` is independently tested but is not mandatory in the coordinator update path. Deployments requiring proof enforcement must add that policy boundary before treating updates as ZKP-attested.
9. **Enrollment identity**: Production registration requires an operator-provisioned per-client public-key allow-list and a signed proof of possession. Coordinator reads, heartbeats, and submissions require signed, timestamped, nonce-protected requests. The legacy shared-token path is available only with the explicit `COORDINATOR_INSECURE_DEV_AUTH=true` flag for disposable development.
