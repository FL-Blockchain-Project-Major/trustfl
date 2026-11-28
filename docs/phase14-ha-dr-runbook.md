# Phase 14 HA/DR runbook and evidence status

**Status: NOT ACCEPTED (2026-11-28).** The repository has unit and simulated
integration coverage, but it has no recorded evidence from the real services
required by the Phase 14 acceptance gate. It must not be described as
production-ready and no PostgreSQL RPO/RTO is claimed.

| Area | Control | Evidence status |
|---|---|---|
| PostgreSQL backup | AES-256-GCM envelope, checksum, and `pg_restore --list` verification | Script/unit validation only |
| Backup freshness | Metric accepts only a `.verified` marker written after authenticated verification | Unit validation only |
| Coordinator | Lease renewal aborts monitor work on loss | SQLite/sequential coverage only; concurrent PostgreSQL fencing required |
| IPFS | SHA-256 retrieval, CID equality, and minimum-replica policy | Mock HTTP coverage only; independent Kubo nodes required |
| Blockchain | Durable outbox and RPC fallback | Simulated JSON-RPC only; signed Hardhat transactions required |
| Redis | Production requires Redis; local fallback is process-local and not globally coordinated | Mock coverage only; multi-process outage/recovery required |

## Backup operation and key rotation

The key file contains one 32-byte AES key as 64 hexadecimal characters or
URL-safe base64. `BACKUP_ENCRYPTION_KEY_ID` is authenticated metadata. Rotate
by creating a new secret-manager key and ID for new backups, retaining old keys
until their archives expire, and restoring an archive with the key selected by
its header.

```bash
export BACKUP_DIR=/secure/offsite/trustfl
export BACKUP_ENCRYPTION_KEY_FILE=/run/secrets/trustfl-backup-key-v2
export BACKUP_ENCRYPTION_KEY_ID=2026-q4
export DATABASE_URL='postgresql://...'
./scripts/backup_postgres.sh
./scripts/verify_backup.sh "$BACKUP_DIR/trustfl-<timestamp>-<nonce>.dump.enc"
```

Wrong keys and modified ciphertext fail AES-GCM authentication. Restore into
an isolated database, run migrations, reconcile round/outbox/on-chain state,
then start only one coordinator.

## Required acceptance evidence

Record commands, service versions, timestamps, and retained logs for: real
PostgreSQL backup/restore (including schema, migration revision, federation,
rounds, updates, outbox, and artifact references); two simultaneous
coordinators with PostgreSQL crash/partition/takeover and stale-write tests;
independent Kubo loss/recovery and partial replication; deployed Hardhat
contracts with signed transaction interruption/reconciliation; multi-process
Redis outage/recovery; and Prometheus alert-expression/delivery tests.

`tests/integration/ha_dr/test_phase14_ha_dr.py` is **not** acceptance evidence:
it uses SQLite, mock IPFS, a simulated JSON-RPC server, and mock Redis.
