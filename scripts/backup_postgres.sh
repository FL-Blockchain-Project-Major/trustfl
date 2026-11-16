#!/usr/bin/env bash
set -euo pipefail

: "${BACKUP_DIR:?BACKUP_DIR must point to protected offsite backup storage}"
: "${BACKUP_ENCRYPTION_KEY_FILE:?BACKUP_ENCRYPTION_KEY_FILE must point to a secret-manager-provided key file}"
: "${DATABASE_URL:?DATABASE_URL is required}"
retention_days="${BACKUP_RETENTION_DAYS:-35}"

umask 077
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$BACKUP_DIR/trustfl-${timestamp}.dump.enc"
manifest="$archive.sha256"
tmp="$(mktemp "${TMPDIR:-/tmp}/trustfl-backup.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL" > "$tmp"
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass "file:$BACKUP_ENCRYPTION_KEY_FILE" \
  -in "$tmp" -out "$archive"
sha256sum "$archive" > "$manifest"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'trustfl-*.dump.enc' -mtime +"$retention_days" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'trustfl-*.dump.enc.sha256' -mtime +"$retention_days" -delete
printf 'Created encrypted backup: %s\n' "$archive"
