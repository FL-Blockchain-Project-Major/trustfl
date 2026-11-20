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
  local url="$1"
  local token="${2:-${API_READ_KEY}}"
  curl --fail --silent --show-error --location \
    -H "Authorization: Bearer ${token}" \
    --connect-timeout 2 --max-time 10 \
    --retry 3 --retry-all-errors --retry-delay 1 "$url"
}

http_get_admin() {
  http_get "$1" "${API_ADMIN_KEY}"
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
  local mode="${2:-poll}"
  local rounds updates transactions

  rounds="$(http_get "http://localhost:8000/rounds/federation/fed-default")" || return 1
  updates="$(http_get "http://localhost:8000/updates/federation/fed-default")" || return 1
  transactions="$(http_get_admin "http://localhost:8000/blockchain/transactions?limit=100")" || return 1

  python3 - "$rounds" "$updates" "$transactions" "$num_clients" "$mode" <<'PY'
import json, os, sys

rounds, updates, transactions, num_clients_str, mode = sys.argv[1:6]
num_clients = int(num_clients_str)

rounds_data     = json.loads(rounds)
updates_data    = json.loads(updates)
txns_data       = json.loads(transactions)

rounds_list  = rounds_data.get("data", [])
updates_list = updates_data.get("data", [])
txns_list    = txns_data.get("data", [])

round_map = {int(r["round_number"]): r for r in rounds_list if "round_number" in r}
finalized = {
    int(r["round_number"])
    for r in rounds_list
    if r.get("status") == "FINALIZED"
}
completed = {
    int(r["round_number"])
    for r in rounds_list
    if r.get("status") == "COMPLETED"
}

expected_clients = {f"client_{i:03d}" for i in range(1, num_clients + 1)}
client_updates_per_round = {}
for r_num in (1, 2, 3):
    r_id = f"fed-default_round{r_num}"
    verified_clients = {
        u["client_id"]
        for u in updates_list
        if u.get("status") in {"VERIFIED", "AGGREGATED"}
        and u.get("round_id") == r_id
        and "client_id" in u
    }
    client_updates_per_round[r_num] = verified_clients

confirmed_finalizations = {
    int(t["entity_id"])
    for t in txns_list
    if t.get("status") == "CONFIRMED"
    and t.get("contract_name") == "TrainingRoundRegistry"
    and t.get("function_name") == "finalizeRound"
    and t.get("entity_type") == "round"
    and str(t.get("entity_id", "")).isdigit()
}

errors = []

# 1. Round finalization checks
missing_rounds = {1, 2, 3} - set(round_map.keys())
if missing_rounds:
    errors.append(f"Missing round records for rounds: {sorted(missing_rounds)}")

non_finalized = {1, 2, 3} - finalized
if non_finalized:
    status_details = [
        f"Round {rn}: status={round_map[rn].get('status', 'MISSING')}"
        for rn in sorted(non_finalized)
        if rn in round_map
    ]
    errors.append(
        f"Expected finalized rounds {{1, 2, 3}}; unfinalized: {sorted(non_finalized)} "
        f"({', '.join(status_details)})"
    )

# 2. Client update verification per round
for r_num in (1, 2, 3):
    observed_clients = client_updates_per_round.get(r_num, set())
    missing = expected_clients - observed_clients
    if missing:
        errors.append(
            f"Round {r_num}: missing verified updates from {sorted(missing)}; "
            f"observed {sorted(observed_clients)}"
        )

# 3. On-chain finalization transaction confirmation
missing_txns = {1, 2, 3} - confirmed_finalizations
if missing_txns:
    errors.append(
        f"Missing confirmed finalizeRound blockchain transactions for rounds {sorted(missing_txns)}; "
        f"observed {sorted(confirmed_finalizations)}"
    )

# 4. Global model artifact presence
for r_num in (1, 2, 3):
    r_obj = round_map.get(r_num, {})
    if not r_obj.get("global_model_artifact_id"):
        errors.append(f"Round {r_num}: missing global_model_artifact_id on round record")

if errors:
    if mode in ("assert", "verbose"):
        print("\n" + "=" * 60, file=sys.stderr)
        print("[-] E2E LIFECYCLE ACCEPTANCE FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  * {err}", file=sys.stderr)
        print("\n--- Diagnostic Dump ---", file=sys.stderr)
        print("Observed Rounds:", file=sys.stderr)
        for r in rounds_list:
            print(f"  Round {r.get('round_number')}: status={r.get('status')} model_version={r.get('model_version')} artifact_id={r.get('global_model_artifact_id')}", file=sys.stderr)
        print("Observed Updates (sample):", file=sys.stderr)
        for u in updates_list[:15]:
            print(f"  Update {u.get('id')}: round={u.get('round_id')} client={u.get('client_id')} status={u.get('status')}", file=sys.stderr)
        if len(updates_list) > 15:
            print(f"  ... ({len(updates_list) - 15} more updates)", file=sys.stderr)
        print("Observed Blockchain Transactions:", file=sys.stderr)
        for t in txns_list:
            print(f"  Tx {t.get('tx_hash', '')[:10]}...: fn={t.get('function_name')} entity={t.get('entity_type')} id={t.get('entity_id')} status={t.get('status')}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
    sys.exit(1)

print(f"Finalized rounds:        {sorted(finalized)}")
print(f"Expected clients:        {sorted(expected_clients)}")
print(f"Confirmed finalizations: {sorted(confirmed_finalizations)}")
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
  until check_lifecycle "$num_clients" "poll"; do
    if (( SECONDS >= lifecycle_deadline )); then
      log "FL lifecycle timed out for FL_NUM_CLIENTS=${num_clients}. Running diagnostic dump:"
      check_lifecycle "$num_clients" "verbose" || true
      fail "FL lifecycle timed out for FL_NUM_CLIENTS=${num_clients}"
    fi
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

  log "Verifying least-privilege authorization gates..."
  # Admin credentials accepted on blockchain transactions
  http_get_admin "http://localhost:8000/blockchain/transactions?limit=10" >/dev/null

  # Read credentials rejected with 403 on admin-only blockchain transactions
  local read_tx_code
  read_tx_code="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${API_READ_KEY}" \
    http://localhost:8000/blockchain/transactions?limit=100)"
  [[ "$read_tx_code" == "403" ]] || fail "Expected 403 for read key on /blockchain/transactions, got $read_tx_code"

  # Unauthenticated request rejected with 401
  local unauth_tx_code
  unauth_tx_code="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' \
    http://localhost:8000/blockchain/transactions?limit=100)"
  [[ "$unauth_tx_code" == "401" ]] || fail "Expected 401 for unauthenticated on /blockchain/transactions, got $unauth_tx_code"

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
