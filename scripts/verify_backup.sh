#!/usr/bin/env bash
set -euo pipefail

archive="${1:?usage: verify_backup.sh BACKUP_FILE}"
[[ -f "$archive" && -f "$archive.sha256" ]] || { echo "Backup or checksum missing" >&2; exit 1; }
sha256sum --check "$archive.sha256"
if [[ -n "${BACKUP_ENCRYPTION_KEY_FILE:-}" && -f "${BACKUP_ENCRYPTION_KEY_FILE}" ]]; then
  if command -v pg_restore >/dev/null 2>&1; then
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -pass "file:$BACKUP_ENCRYPTION_KEY_FILE" \
      -in "$archive" | pg_restore --list >/dev/null
  else
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -pass "file:$BACKUP_ENCRYPTION_KEY_FILE" \
      -in "$archive" | head -c 1 >/dev/null
  fi
fi
echo "Backup checksum verified: $archive"
