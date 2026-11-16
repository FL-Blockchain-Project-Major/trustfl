# Backup and restore

## Schedule and retention

Run `scripts/backup_postgres.sh` at least hourly for production metadata,
retain daily backups for 35 days and monthly backups for 12 months, and copy
encrypted archives to immutable offsite storage. WAL archiving/PITR must be
enabled by the PostgreSQL provider; the exact bucket and retention policy are
deployment-specific.

The backup contains database metadata, round state, accepted updates, proofs,
model pointers, and transactional outbox records. It does not contain client
private keys, bearer credentials, or raw datasets. Artifact objects and pinned
ZKP verification artifacts require separate versioned, encrypted object-storage
backups. The encryption key is supplied through a secret manager and is never
stored beside the archive.

```bash
export BACKUP_DIR=/secure/offsite/trustfl
export BACKUP_ENCRYPTION_KEY_FILE=/run/secrets/trustfl-backup-key
export DATABASE_URL='postgresql://...'
./scripts/backup_postgres.sh
./scripts/verify_backup.sh "$BACKUP_DIR/trustfl-<timestamp>.dump.enc"
```

`BACKUP_RETENTION_DAYS` defaults to 35 for the local staging directory; the
offsite immutable store must enforce the longer monthly retention policy.

Restore into an isolated PostgreSQL instance first:

```bash
./scripts/restore_postgres.sh "$BACKUP_DIR/trustfl-<timestamp>.dump.enc"
alembic upgrade head
```

Do not start coordinators until reconciliation confirms round states, model
hashes, outbox idempotency keys, and on-chain transaction status. Restore tests
must use a disposable database and never production credentials.
