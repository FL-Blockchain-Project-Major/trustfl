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
  curl --fail --silent --show-error --location \
    -H "Authorization: Bearer ${API_READ_KEY}" \
    --connect-timeout 2 --max-time 10 \
    --retry 3 --retry-all-errors --retry-delay 1 "$1"
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
  local rounds updates transactions
  rounds="$(http_get "http://localhost:8000/rounds/federation/fed-default")" || return 1
  updates="$(http_get "http://localhost:8000/updates/federation/fed-default")" || return 1
  transactions="$(http_get "http://localhost:8000/blockchain/transactions?limit=100")" || return 1

  python3 - "$rounds" "$updates" "$transactions" <<'PY'
import json
import os
import sys

rounds, updates, transactions = map(json.loads, sys.argv[1:])

finalized = {
    int(r["round_number"])
    for r in rounds.get("data", [])
    if r.get("status") == "FINALIZED"
}
if not {1, 2, 3}.issubset(finalized):
    sys.exit(
        f"Expected finalized rounds 1, 2, 3; "
        f"observed {sorted(finalized)}"
    )

num_clients = int(os.environ.get("FL_NUM_CLIENTS", "3"))
expected_clients = {
    f"client_{i:03d}" for i in range(1, num_clients + 1)
}

for round_number in (1, 2, 3):
    round_id = f"fed-default_round{round_number}"
    round_clients = {
        u["client_id"]
        for u in updates.get("data", [])
        if u.get("status") in {"VERIFIED", "AGGREGATED"}
        and u.get("round_id") == round_id
        and "client_id" in u
    }

    missing = expected_clients - round_clients
    if missing:
        sys.exit(
            f"Round {round_number}: missing clients "
            f"{sorted(missing)}; observed {sorted(round_clients)}"
        )

confirmed_finalizations = {
    int(t["entity_id"])
    for t in transactions.get("data", [])
    if t.get("status") == "CONFIRMED"
    and t.get("contract_name") == "TrainingRoundRegistry"
    and t.get("function_name") == "finalizeRound"
    and t.get("entity_type") == "round"
    and str(t.get("entity_id", "")).isdigit()
}

if not {1, 2, 3}.issubset(confirmed_finalizations):
    sys.exit(
        "Missing confirmed finalizeRound transactions for rounds "
        f"1, 2, 3; observed {sorted(confirmed_finalizations)}"
    )

print(f"Finalized rounds: {sorted(finalized)}")
print(f"Expected clients: {sorted(expected_clients)}")
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
until check_lifecycle; do
  exited_failed="$(docker compose ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | grep -v 'client-init' | grep -v 'contract-deployer' | grep -E 'exited ([1-9]|1[0-9]|2[0-9])' || true)"
  if [[ -n "$exited_failed" ]]; then
    echo "Error: Container(s) exited unexpectedly: $exited_failed"
    docker compose logs --no-color
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "FL lifecycle timed out"
    exit 1
  fi
  sleep 5
done

echo "Verifying dashboard..."
dashboard="$(curl --fail --silent --show-error --location -H "Authorization: Bearer ${DASHBOARD_ACCESS_KEY}" "http://localhost:3000/api/dashboard/federations/")"

unauthenticated="$(curl --silent --show-error --location -o /dev/null -w '%{http_code}' http://localhost:8000/federations/)"
[[ "$unauthenticated" == "401" ]] || { echo "Expected unauthenticated API request to return 401, got $unauthenticated"; exit 1; }

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

check_lifecycle

echo "TrustFL Compose E2E PASSED"

