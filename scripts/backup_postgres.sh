#!/usr/bin/env bash
set -euo pipefail

: "${BACKUP_DIR:?BACKUP_DIR must point to protected offsite backup storage}"
: "${BACKUP_ENCRYPTION_KEY_FILE:?BACKUP_ENCRYPTION_KEY_FILE must point to a secret-manager-provided key file}"
: "${DATABASE_URL:?DATABASE_URL is required}"
retention_days="${BACKUP_RETENTION_DAYS:-35}"
: "${BACKUP_ENCRYPTION_KEY_ID:?BACKUP_ENCRYPTION_KEY_ID identifies the active rotated key}"

umask 077
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
archive="$BACKUP_DIR/trustfl-${timestamp}.dump.enc"
manifest="$archive.sha256"
tmp="$(mktemp "${TMPDIR:-/tmp}/trustfl-backup.XXXXXX")"
encrypted_tmp="$(mktemp "$BACKUP_DIR/.trustfl-backup.XXXXXX")"
manifest_tmp="$(mktemp "$BACKUP_DIR/.trustfl-manifest.XXXXXX")"
trap 'rm -f "$tmp" "$encrypted_tmp" "$manifest_tmp"' EXIT

pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL" > "$tmp"
python3 "$(dirname "$0")/backup_crypto.py" encrypt "$tmp" "$encrypted_tmp" \
  --key-file "$BACKUP_ENCRYPTION_KEY_FILE" --key-id "$BACKUP_ENCRYPTION_KEY_ID"
sha256sum "$encrypted_tmp" | sed "s|$encrypted_tmp|$archive|" > "$manifest_tmp"
# A completed archive becomes visible only after encryption and manifest creation.
mv "$encrypted_tmp" "$archive"
mv "$manifest_tmp" "$manifest"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'trustfl-*.dump.enc' -mtime +"$retention_days" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'trustfl-*.dump.enc.sha256' -mtime +"$retention_days" -delete
printf 'Created encrypted backup: %s\n' "$archive"
