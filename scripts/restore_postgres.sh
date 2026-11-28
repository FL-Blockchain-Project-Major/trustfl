#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_ENCRYPTION_KEY_FILE:?BACKUP_ENCRYPTION_KEY_FILE must point to a secret-manager-provided key file}"

archive="${1:?usage: restore_postgres.sh BACKUP_FILE}"
manifest="$archive.sha256"
[[ -f "$archive" && -f "$manifest" ]] || { echo "Backup or checksum missing" >&2; exit 1; }
sha256sum --check "$manifest"
tmp="$(mktemp "${TMPDIR:-/tmp}/trustfl-restore.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
python3 "$(dirname "$0")/backup_crypto.py" decrypt "$archive" "$tmp" \
  --key-file "$BACKUP_ENCRYPTION_KEY_FILE"
pg_restore --exit-on-error --clean --if-exists --no-owner --no-acl --dbname="$DATABASE_URL" "$tmp"
echo "Restore completed; run reconciliation before enabling coordinators."
