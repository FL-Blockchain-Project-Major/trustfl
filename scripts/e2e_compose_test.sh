#!/usr/bin/env bash
# TrustFL Compose E2E Test Script
#
# Tests the full federated-learning lifecycle using Docker Compose.
# Runs the stack with FL_NUM_CLIENTS=1, 2, and 3 in sequence (or a single
# count if FL_NUM_CLIENTS is set in the environment).
#
# Usage:
#   ./scripts/e2e_compose_test.sh           # tests 1, 2, 3 clients
#   FL_NUM_CLIENTS=2 ./scripts/e2e_compose_test.sh  # tests only 2 clients
#
# Requirements:
#   - Docker 24+ with Compose plugin
#   - The stack must be fully torn down before running
#
# Exit code: 0 if all tests pass, 1 on first failure.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

API_READ_KEY="${API_READ_KEY:-trustfl-read-dev}"
API_WRITE_KEY="${API_WRITE_KEY:-trustfl-write-dev}"
API_ADMIN_KEY="${API_ADMIN_KEY:-trustfl-admin-dev}"
DASHBOARD_ACCESS_KEY="${DASHBOARD_ACCESS_KEY:-trustfl-dashboard-dev}"
COORDINATOR_ENROLLMENT_TOKEN="${COORDINATOR_ENROLLMENT_TOKEN:-trustfl-coordinator-dev}"
COORDINATOR_HOST_PORT="${COORDINATOR_HOST_PORT:-18100}"

# Use explicit counts if FL_NUM_CLIENTS is set; otherwise test 1, 2, and 3
if [[ -n "${FL_NUM_CLIENTS:-}" ]]; then
  CLIENT_COUNTS=("$FL_NUM_CLIENTS")
else
  CLIENT_COUNTS=(1 2 3)
fi

# ── Helpers ──────────────────────────────────────────────────────────────────

log() { echo "[e2e] $*"; }
fail() { echo "[e2e] FAIL: $*" >&2; exit 1; }

http_get() {
  curl --fail --silent --show-error --location \
    -H "Authorization: Bearer ${API_READ_KEY}" \
    --connect-timeout 2 --max-time 10 \
    --retry 3 --retry-all-errors --retry-delay 1 "$1"
}

wait_for_url() {
  local url="$1" deadline=$((SECONDS + 180))
  until http_get "$url" >/dev/null 2>&1; do
    (( SECONDS >= deadline )) && fail "Timed out waiting for: $url"
    sleep 3
  done
  log "Ready: $url"
}

wait_for_coordinator() {
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    local cid
    cid="$(docker compose ps -q coordinator 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      if http_get "http://localhost:${COORDINATOR_HOST_PORT}/health" >/dev/null 2>&1; then
        log "Coordinator is ready."
        return 0
      fi
      local state
      state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
      if [[ "$state" == "exited" ]]; then
        docker compose logs --no-color --tail=50 coordinator >&2 || true
        fail "Coordinator exited unexpectedly."
      fi
    fi
    sleep 3
  done
  fail "Timed out waiting for coordinator."
}

check_lifecycle() {
  local num_clients="$1"
  local rounds updates transactions

  rounds="$(http_get "http://localhost:8000/rounds/federation/fed-default")" || return 1
  updates="$(http_get "http://localhost:8000/updates/federation/fed-default")" || return 1
  transactions="$(http_get "http://localhost:8000/blockchain/transactions?limit=100")" || return 1

  python3 - "$rounds" "$updates" "$transactions" "$num_clients" <<'PY'
import json, os, sys

rounds, updates, transactions, num_clients_str = sys.argv[1:]
num_clients = int(num_clients_str)

rounds_data     = json.loads(rounds)
updates_data    = json.loads(updates)
txns_data       = json.loads(transactions)

finalized = {
    int(r["round_number"])
    for r in rounds_data.get("data", [])
    if r.get("status") == "FINALIZED"
}
if not {1, 2, 3} <= finalized:
    sys.exit(f"Expected finalized rounds {{1, 2, 3}}, got {sorted(finalized)}")

expected_clients = {f"client_{i:03d}" for i in range(1, num_clients + 1)}
for round_number in (1, 2, 3):
    round_clients = {
        u["client_id"]
        for u in updates_data.get("data", [])
        if u.get("status") in {"VERIFIED", "AGGREGATED"}
        and u.get("round_id") == f"fed-default_round{round_number}"
        and "client_id" in u
    }
    if not expected_clients <= round_clients:
        sys.exit(
            f"Round {round_number}: expected updates from {sorted(expected_clients)}, "
            f"got {sorted(round_clients)}"
        )

confirmed = {
    int(t["entity_id"])
    for t in txns_data.get("data", [])
    if t.get("status") == "CONFIRMED"
    and t.get("contract_name") == "TrainingRoundRegistry"
    and t.get("function_name") == "finalizeRound"
    and t.get("entity_type") == "round"
    and str(t.get("entity_id", "")).isdigit()
}
if not {1, 2, 3} <= confirmed:
    sys.exit(f"Expected confirmed finalizeRound txns for rounds {{1,2,3}}, got {sorted(confirmed)}")

print(f"Finalized rounds:        {sorted(finalized)}")
print(f"Expected clients:        {sorted(expected_clients)}")
print(f"Confirmed finalizations: {sorted(confirmed)}")
PY
}

run_test() {
  local num_clients="$1"
  local project="trustfl-e2e-n${num_clients}-$$"

  log "════════════════════════════════════════════"
  log "Testing FL_NUM_CLIENTS=${num_clients}"
  log "════════════════════════════════════════════"

  export COMPOSE_PROJECT_NAME="$project"
  export FL_NUM_CLIENTS="$num_clients"
  export FL_MIN_CLIENTS="$num_clients"
  export COORDINATOR_HOST_PORT="$COORDINATOR_HOST_PORT"
  export API_READ_KEY API_WRITE_KEY API_ADMIN_KEY DASHBOARD_ACCESS_KEY
  export COORDINATOR_ENROLLMENT_TOKEN
  export COORDINATOR_INSECURE_DEV_AUTH=true
  export FL_DATASET_DIR="${FL_DATASET_DIR:-./datasets/sample}"

  local cleanup_done=0
  cleanup() {
    if [[ "$cleanup_done" -eq 0 ]]; then
      cleanup_done=1
      local status=$?
      if [[ "$status" -ne 0 ]]; then
        log "Test FAILED for FL_NUM_CLIENTS=${num_clients}"
        docker compose ps --all || true
        docker compose logs --no-color --tail=200 || true
      fi
      docker compose down --volumes --remove-orphans 2>/dev/null || true
    fi
  }
  trap cleanup EXIT

  # Ensure sample dataset exists (clients fall back to synthetic training if empty)
  if [[ ! -d "$FL_DATASET_DIR" ]]; then
    if command -v python3 &>/dev/null; then
      python3 scripts/generate_sample_dataset.py --out-dir "$FL_DATASET_DIR" --num-images 30 \
        2>/dev/null || mkdir -p "${FL_DATASET_DIR}/images" "${FL_DATASET_DIR}/annotations"
    else
      mkdir -p "${FL_DATASET_DIR}/images" "${FL_DATASET_DIR}/annotations"
    fi
  fi

  log "Starting Compose stack (FL_NUM_CLIENTS=${num_clients})..."
  docker compose up --build -d

  log "Waiting for services..."
  wait_for_url "http://localhost:8000/health/"
  wait_for_url "http://localhost:3000/"
  wait_for_coordinator

  log "Waiting for FL lifecycle to complete (up to 10 min)..."
  local lifecycle_deadline=$((SECONDS + 600))
  until check_lifecycle "$num_clients" 2>/dev/null; do
    (( SECONDS >= lifecycle_deadline )) && fail "FL lifecycle timed out for FL_NUM_CLIENTS=${num_clients}"
    sleep 5
  done

  log "Verifying dashboard API..."
  local dashboard
  dashboard="$(curl --fail --silent --show-error --location \
    -H "Authorization: Bearer ${DASHBOARD_ACCESS_KEY}" \
    "http://localhost:3000/api/dashboard/federations/")"
  python3 - "$dashboard" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
if payload.get("success") is not True:
    sys.exit(f"Dashboard API unsuccessful: {payload!r}")
data = payload.get("data")
if not isinstance(data, list):
    sys.exit(f"Dashboard federation data is not a list: {data!r}")
if not any(isinstance(i, dict) and i.get("id") == "fed-default" for i in data):
    sys.exit(f"fed-default not visible in dashboard data: {data!r}")
print("Dashboard federation visibility verified.")
PY

  log "Verifying unauthenticated API returns 401..."
  local code
  code="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' \
    http://localhost:8000/federations/)"
  [[ "$code" == "401" ]] || fail "Expected 401 for unauthenticated request, got $code"

  log "✓ FL_NUM_CLIENTS=${num_clients} PASSED"
  cleanup
  trap - EXIT
}

# ── Main ─────────────────────────────────────────────────────────────────────

PASSED=()
FAILED=()

for n in "${CLIENT_COUNTS[@]}"; do
  if run_test "$n"; then
    PASSED+=("FL_NUM_CLIENTS=$n")
  else
    FAILED+=("FL_NUM_CLIENTS=$n")
    break   # stop on first failure to keep logs readable
  fi
done

echo ""
echo "════════════════════════════════════════════"
echo " TrustFL Compose E2E Results"
echo "════════════════════════════════════════════"
for p in "${PASSED[@]}"; do echo " ✓ PASS  $p"; done
for f in "${FAILED[@]}"; do echo " ✗ FAIL  $f"; done
echo "════════════════════════════════════════════"

[[ "${#FAILED[@]}" -eq 0 ]] || exit 1
echo "All E2E tests PASSED."
