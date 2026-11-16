#!/usr/bin/env bash
set -euo pipefail

archive="${1:?usage: verify_backup.sh BACKUP_FILE}"
[[ -f "$archive" && -f "$archive.sha256" ]] || { echo "Backup or checksum missing" >&2; exit 1; }
sha256sum --check "$archive.sha256"
echo "Backup checksum verified: $archive"
