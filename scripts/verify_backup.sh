#!/usr/bin/env bash
set -euo pipefail

archive="${1:?usage: verify_backup.sh BACKUP_FILE}"
[[ -f "$archive" && -f "$archive.sha256" ]] || { echo "Backup or checksum missing" >&2; exit 1; }
sha256sum --check "$archive.sha256"
[[ -n "${BACKUP_ENCRYPTION_KEY_FILE:-}" && -f "${BACKUP_ENCRYPTION_KEY_FILE}" ]] || {
  echo "BACKUP_ENCRYPTION_KEY_FILE is required for authenticated verification" >&2; exit 1;
}
command -v pg_restore >/dev/null 2>&1 || { echo "pg_restore is required" >&2; exit 1; }
tmp="$(mktemp "${TMPDIR:-/tmp}/trustfl-verify.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
python3 "$(dirname "$0")/backup_crypto.py" decrypt "$archive" "$tmp" \
  --key-file "$BACKUP_ENCRYPTION_KEY_FILE"
pg_restore --list "$tmp" >/dev/null
# The readiness metric trusts only a marker written after authenticated decrypt + pg_restore parse.
verified_tmp="$(mktemp "$(dirname "$archive")/.trustfl-verified.XXXXXX")"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(sha256sum "$archive" | awk '{print $1}')" > "$verified_tmp"
mv "$verified_tmp" "$archive.verified"
echo "Backup checksum verified: $archive"
