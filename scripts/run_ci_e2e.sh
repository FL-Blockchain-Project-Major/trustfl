#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Backup .env if present
if [[ -f .env ]]; then
  cp .env .env.scenario1
fi

cleanup() {
  local status=$?
  if [[ -f .env.scenario1 ]]; then
    cp .env.scenario1 .env && rm -f .env.scenario1
  fi
  if [[ "$status" -ne 0 ]]; then
    docker compose ps --all || true
    docker compose logs --no-color --tail=500 || true
  fi
  docker compose down --volumes --remove-orphans || true
  exit "$status"
}
trap cleanup EXIT

export COMPOSE_PROJECT_NAME="trustfl-ci-local"
export COORDINATOR_HOST_PORT=18100
export API_AUTH_REQUIRED=true API_READ_KEY=ci-read API_WRITE_KEY=ci-write API_ADMIN_KEY=ci-admin
export DASHBOARD_ACCESS_KEY=ci-dashboard COORDINATOR_ENROLLMENT_TOKEN=ci-coordinator
export FL_DATASET_DIR=./datasets/sample
export FL_NUM_CLIENTS=3
export FL_MIN_CLIENTS=3
export FL_FEDERATION_ID=fed-default
export FL_NUM_ROUNDS=3
export FL_MAX_CLIENT_WEIGHT_SHARE=0.5
export FL_MAX_UPDATE_NORM=1.0
export COORDINATOR_INSECURE_DEV_AUTH=true

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
  local deadline=$((SECONDS + 180))
  until http_get "$1" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for: $1"
      return 1
    fi
    sleep 3
  done
  echo "Ready: $1"
}

wait_for_coordinator() {
  local deadline=$((SECONDS + 180))
  local container_id state

  while (( SECONDS < deadline )); do
    container_id="$(docker compose ps -q coordinator 2>/dev/null || true)"

    if [[ -n "$container_id" ]]; then
      if http_get "http://localhost:${COORDINATOR_HOST_PORT}/health" >/dev/null 2>&1; then
        echo "Coordinator is ready."
        return 0
      fi

      state="$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$container_id" 2>/dev/null || true)"
      case "$state" in
        "exited 0") echo "Coordinator completed with exit code 0."; return 0 ;;
        exited*)    echo "Coordinator exited unexpectedly: $state"; return 1 ;;
      esac
    fi

    sleep 3
  done

  echo "Timed out waiting for coordinator."
  return 1
}

check_lifecycle() {
  local mode="${1:-poll}"
  local rounds updates transactions
  rounds="$(http_get "http://localhost:8000/rounds/federation/fed-default")" || return 1
  updates="$(http_get "http://localhost:8000/updates/federation/fed-default")" || return 1
  transactions="$(http_get_admin "http://localhost:8000/blockchain/transactions?limit=100")" || return 1

  python3 - "$rounds" "$updates" "$transactions" "$mode" <<'PY'
import json
import os
import sys

rounds, updates, transactions = map(json.loads, sys.argv[1:4])
mode = sys.argv[4] if len(sys.argv) > 4 else "poll"

rounds_list = rounds.get("data", [])
updates_list = updates.get("data", [])
txns_list = transactions.get("data", [])

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

num_clients = int(os.environ.get("FL_NUM_CLIENTS", "3"))
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

echo "Generating sample dataset (30 mock images for 3 clients)..."
python3 scripts/generate_sample_dataset.py \
  --output-dir ./datasets/sample \
  --train-samples 30 \
  --val-samples 3

cat > .env <<'ENVEOF'
POSTGRES_USER=trustfl
POSTGRES_PASSWORD=trustfl
POSTGRES_DB=trustfl
ENVIRONMENT=development
FL_FEDERATION_ID=fed-default
FL_NUM_ROUNDS=3
FL_NUM_CLIENTS=3
FL_MIN_CLIENTS=3
FL_MAX_CLIENT_WEIGHT_SHARE=0.5
FL_MAX_UPDATE_NORM=1.0
FL_LOCAL_EPOCHS=1
FL_MAX_SAMPLES=50
FL_POLL_INTERVAL_SECONDS=3.0
COORDINATOR_REQUIRE_SIGNATURES=true
COORDINATOR_INSECURE_DEV_AUTH=true
ENVEOF

echo "Starting Compose stack (FL_NUM_CLIENTS=3, FL_FEDERATION_ID=fed-default, FL_NUM_ROUNDS=3)..."
docker compose up --build -d

echo "Waiting for services..."
wait_for_url "http://localhost:8000/health/"
wait_for_url "http://localhost:3000/"
wait_for_coordinator

docker compose exec -T db pg_isready \
  -U "${POSTGRES_USER:-trustfl}" -d "${POSTGRES_DB:-trustfl}"

docker compose exec -T ipfs \
  wget -qO- --post-data= http://localhost:5001/api/v0/id >/dev/null

docker compose exec -T hardhat node -e "
  fetch('http://localhost:8545', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'net_version', params: []})
  })
    .then(r => process.exit(r.ok ? 0 : 1))
    .catch(() => process.exit(1));
"

echo "Waiting for signed FL lifecycle..."
deadline=$((SECONDS + 600))
until check_lifecycle "poll"; do
  exited_failed="$(docker compose ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | grep -v 'client-init' | grep -v 'contract-deployer' | grep -E 'exited ([1-9]|1[0-9]|2[0-9])' || true)"
  if [[ -n "$exited_failed" ]]; then
    echo "Error: Container(s) exited unexpectedly: $exited_failed"
    check_lifecycle "verbose" || true
    docker compose logs --no-color
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "FL lifecycle timed out after 600s. Running diagnostic dump:"
    check_lifecycle "verbose" || true
    docker compose logs --no-color
    exit 1
  fi
  sleep 5
done

echo "Verifying dashboard..."
dashboard="$(curl --fail --silent --show-error --location -H "Authorization: Bearer ${DASHBOARD_ACCESS_KEY}" "http://localhost:3000/api/dashboard/federations/")"

unauthenticated="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' http://localhost:8000/federations/)"
[[ "$unauthenticated" == "401" ]] || { echo "Expected unauthenticated API request to return 401, got $unauthenticated"; exit 1; }

echo "Verifying least-privilege authorization gates..."
# Positive test: admin credentials accepted on admin-only blockchain transactions
http_get_admin "http://localhost:8000/blockchain/transactions?limit=10" >/dev/null

# Negative test: read credentials rejected with 403 on admin-only blockchain transactions
read_tx_code="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer ${API_READ_KEY}" \
  http://localhost:8000/blockchain/transactions?limit=100)"
[[ "$read_tx_code" == "403" ]] || { echo "Expected 403 for read key on /blockchain/transactions, got $read_tx_code"; exit 1; }

# Negative test: unauthenticated request on /blockchain/transactions rejected with 401
unauth_tx_code="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' \
  http://localhost:8000/blockchain/transactions?limit=100)"
[[ "$unauth_tx_code" == "401" ]] || { echo "Expected 401 for unauthenticated on /blockchain/transactions, got $unauth_tx_code"; exit 1; }

python3 - "$dashboard" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
data = payload.get("data")

if payload.get("success") is not True:
    sys.exit(f"Dashboard API unsuccessful: {payload!r}")
if not isinstance(data, list):
    sys.exit(f"Dashboard federation data is not a list: {data!r}")
if not any(isinstance(i, dict) and i.get("id") == "fed-default" for i in data):
    sys.exit(f"fed-default not visible in dashboard data: {data!r}")

print("Dashboard federation visibility verified.")
PY

check_lifecycle "assert"

echo "TrustFL Compose E2E PASSED"

