#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_ENCRYPTION_KEY_FILE:?BACKUP_ENCRYPTION_KEY_FILE must point to a secret-manager-provided key file}"

archive="${1:?usage: restore_postgres.sh BACKUP_FILE}"
manifest="$archive.sha256"
[[ -f "$archive" && -f "$manifest" ]] || { echo "Backup or checksum missing" >&2; exit 1; }
sha256sum --check "$manifest"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass "file:$BACKUP_ENCRYPTION_KEY_FILE" \
  -in "$archive" | pg_restore --clean --if-exists --no-owner --no-acl --dbname="$DATABASE_URL"
echo "Restore completed; run reconciliation before enabling coordinators."
