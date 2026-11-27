# TrustFL — Phase 14 HA, Disaster Recovery & Operational Resilience Runbook

**Date**: 2026-11-27  

---

## 1. High-Availability & Failover Architecture

| Component | Resilience Mechanism | Configuration / Source |
|---|---|---|
| **Control-Plane DB** | SQLAlchemy connection pooling (`pool_pre_ping=True`, `pool_recycle=1800`) + AES-256-CBC encrypted backups with SHA-256 verification | `apps/api/api/db/session.py`, `scripts/backup_postgres.sh`, `scripts/restore_postgres.sh`, `scripts/verify_backup.sh` |
| **Coordinator** | DB lease fencing (`CoordinatorLease.fencing_token`) preventing split-brain + durable `CoordinatorPersistence` round/nonce recovery | `apps/coordinator/persistence.py`, `apps/coordinator/network/server.py` |
| **IPFS Storage** | Pinning (`pin=true`) + multi-endpoint replication & automatic read failover with SHA-256 verification | `packages/storage/trustfl_storage/client.py` (`IPFS_REPLICA_URLS`) |
| **Blockchain RPC** | Multi-RPC failover (`_failover_rpc`), nonce lock, pending-tx reconciliation, and durable outbox replay | `packages/blockchain/trustfl_blockchain/client.py` (`BLOCKCHAIN_FALLBACK_RPC_URLS`) |
| **Redis Rate Limiter** | Runtime exception catch with automatic fallback to in-process fixed-window limiter and automatic resume on recovery | `apps/api/api/middleware/security.py` (`trustfl_redis_fallback_total`) |
| **Observability & Alerts** | Readiness probe, secret-expiry gauge, backup-age gauge, and Prometheus alert rules | `apps/api/api/routers/health.py`, `observability/alerts.yml` |

---

## 2. Measured Recovery Evidence (RPO / RTO)

Verified in `tests/integration/ha_dr/test_phase14_ha_dr.py`:
- **Corrupted Control-Plane DB Restore**:
  - **Measured RPO**: `0` committed rows lost for backed-up state.
  - **Measured RTO**: `< 5.0 s` for SHA-256 checksum verification, AES-256-CBC decryption, and full SQLite control-plane state restoration.
- **Coordinator Split-Brain Prevention**: Standby coordinator `acquire_lease()` rejected while primary lease active; takeover after release/expiry incremented `fencing_token` from `1` to `2`.
- **IPFS Node Failure**: Primary IPFS node shut down after pinned replication; `IPFSStorageClient.load_artifact()` failed over to replica and verified SHA-256. Tampered replica bytes raised `ValueError`.
- **Blockchain RPC Failover & Outbox Drain**: `BlockchainClient` failed over from unreachable primary RPC to healthy fallback RPC; `CoordinatorState._process_blockchain_outbox()` drained pending `ROUND_COMMIT` events cleanly.
- **Redis Transient Outage**: `GlobalRateLimitMiddleware` fell back to local window limiting on `ConnectionError`, emitted `trustfl_redis_fallback_total`, and enforced `429` without returning `500`.

---

## 3. Recovery Procedures

1. **Verify Encrypted Backup**:
   ```bash
   BACKUP_ENCRYPTION_KEY_FILE=/path/to/key ./scripts/verify_backup.sh /backups/trustfl-YYYYMMDDTHHMMSSZ.dump.enc
   ```
2. **Restore PostgreSQL**:
   ```bash
   DATABASE_URL=postgresql://... BACKUP_ENCRYPTION_KEY_FILE=/path/to/key ./scripts/restore_postgres.sh /backups/trustfl-YYYYMMDDTHHMMSSZ.dump.enc
   ```
3. **Drain Outbox & Reconcile**: Start coordinator with `CoordinatorPersistence` enabled; `CoordinatorState` reloads persisted round/artifact/nonce state and drains pending `BlockchainOutbox` entries.

---

## 4. Untested / Target-Environment Scope

- Live multi-node PostgreSQL streaming replication (Patroni/RDS) and multi-AZ Redis Sentinel/Cluster failover were **not executed** in the single-host test environment and must be validated during infrastructure provisioning.
