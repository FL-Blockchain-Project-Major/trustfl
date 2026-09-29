#!/usr/bin/env bash
#
# Build script for TrustFL ZKP circuit.
# Requires: circom (>= 2.1.5) on PATH, and npx snarkjs available.
#
# Produces:
#   artifacts/update_commitment.wasm  – WASM witness calculator
#   artifacts/update_commitment.r1cs  – R1CS constraint system
#   artifacts/pot12_final.ptau        – Powers of tau (small ceremony)
#   artifacts/update_commitment.zkey  – Groth16 proving key
#   artifacts/verification_key.json   – Groth16 verification key

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="$DIR/artifacts"
CIRCUITS="$DIR/circuits"
mkdir -p "$ARTIFACTS"

echo "=== [1] Compile Circom circuit ==="
circom "$CIRCUITS/update_commitment.circom" \
  --r1cs --wasm --sym \
  --output "$ARTIFACTS" \
  --include "$DIR/node_modules"

echo "=== [2] Powers of Tau ceremony (pot12) ==="
if [ ! -f "$ARTIFACTS/pot12_final.ptau" ]; then
  npx snarkjs powersoftau new bn128 12 "$ARTIFACTS/pot12_0000.ptau" -v
  npx snarkjs powersoftau contribute "$ARTIFACTS/pot12_0000.ptau" "$ARTIFACTS/pot12_0001.ptau" --name="TrustFL Init" -e="trustfl_phase1_entropy_$(date +%s)"
  npx snarkjs powersoftau prepare phase2 "$ARTIFACTS/pot12_0001.ptau" "$ARTIFACTS/pot12_final.ptau" -v
fi

echo "=== [3] Generate zkey (Groth16 setup) ==="
WASM_DIR="$ARTIFACTS/update_commitment_js"
npx snarkjs groth16 setup "$ARTIFACTS/update_commitment.r1cs" "$ARTIFACTS/pot12_final.ptau" "$ARTIFACTS/update_commitment_0000.zkey"
npx snarkjs zkey contribute "$ARTIFACTS/update_commitment_0000.zkey" "$ARTIFACTS/update_commitment.zkey" --name="TrustFL Phase 2" -e="trustfl_phase2_entropy_$(date +%s)"

echo "=== [4] Export verification key ==="
npx snarkjs zkey export verificationkey "$ARTIFACTS/update_commitment.zkey" "$ARTIFACTS/verification_key.json"

echo "=== Build complete ==="
echo "Artifacts in: $ARTIFACTS"
