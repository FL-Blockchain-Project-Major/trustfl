/**
 * TrustFL ZKP Test Suite
 * ======================
 * Tests the ZKP subsystem using the Poseidon commitment scheme.
 *
 * NOTE: These tests use the Poseidon hash natively via circomlibjs.
 * They validate the commitment computation, witness building, proof semantics,
 * and rejection of invalid proofs — all without requiring a Groth16 circuit.
 *
 * A full Groth16 proof (via the .wasm/.zkey artifacts) is available after
 * running `bash scripts/build.sh` (requires circom compiler >= 2.1.5).
 */

import { buildPoseidon } from "circomlibjs";
import assert from "assert";
import { computeCommitment, buildWitness, extractProofMetadata } from "../src/zkp.js";

// ---------------------------------------------------------------------------
// Helper: check that a fake proof is detected
// ---------------------------------------------------------------------------
async function poseidonHash(inputs) {
  const poseidon = await buildPoseidon();
  const hash = poseidon(inputs.map(BigInt));
  return poseidon.F.toString(hash);
}

// Simulate the circuit constraint: Poseidon(pub..., private) == publicCommitment
function circuitSatisfied(witness) {
  return witness !== null; // witness validity is the commitment check below
}

async function checkWitnessSatisfied({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment, publicCommitment }) {
  const computed = await poseidonHash([clientId, federationId, roundId, modelVersion, privateUpdateCommitment]);
  return computed === publicCommitment.toString();
}

// ===========================================================================
// Test cases
// ===========================================================================

let passed = 0;
let failed = 0;
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

// ---------------------------------------------------------------------------
// Test 1: Valid commitment — circuit should be satisfied
// ---------------------------------------------------------------------------
test("Valid commitment satisfies circuit constraint", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });
  const witness = buildWitness({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment, publicCommitment });

  const satisfied = await checkWitnessSatisfied(witness);
  assert.strictEqual(satisfied, true, "Valid witness should satisfy circuit");

  console.log(`  publicCommitment = ${publicCommitment.slice(0, 32)}...`);
});

// ---------------------------------------------------------------------------
// Test 2: Wrong round — circuit constraint should NOT be satisfied
// ---------------------------------------------------------------------------
test("Wrong round — commitment mismatch detected", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  // Commitment was made for round 3
  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  // Prover tries to claim it's for round 99
  const tamperedWitness = buildWitness({
    clientId, federationId,
    roundId: 99n,   // ← wrong round
    modelVersion, privateUpdateCommitment, publicCommitment,
  });

  const satisfied = await checkWitnessSatisfied(tamperedWitness);
  assert.strictEqual(satisfied, false, "Wrong round should fail circuit check");
});

// ---------------------------------------------------------------------------
// Test 3: Wrong client — circuit constraint should NOT be satisfied
// ---------------------------------------------------------------------------
test("Wrong client — commitment mismatch detected", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  // Impersonator uses a different clientId
  const tamperedWitness = buildWitness({
    clientId: 9999n,  // ← wrong client
    federationId, roundId, modelVersion,
    privateUpdateCommitment, publicCommitment,
  });

  const satisfied = await checkWitnessSatisfied(tamperedWitness);
  assert.strictEqual(satisfied, false, "Wrong client should fail circuit check");
});

// ---------------------------------------------------------------------------
// Test 4: Wrong private commitment — knowledge proof fails
// ---------------------------------------------------------------------------
test("Wrong private commitment — knowledge proof fails", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  // Prover does not know the secret; guesses a different value
  const guessedCommitment = 0xbaaadn;
  const tamperedWitness = buildWitness({
    clientId, federationId, roundId, modelVersion,
    privateUpdateCommitment: guessedCommitment,  // ← wrong secret
    publicCommitment,
  });

  const satisfied = await checkWitnessSatisfied(tamperedWitness);
  assert.strictEqual(satisfied, false, "Wrong private commitment should fail");
});

// ---------------------------------------------------------------------------
// Test 5: Wrong model version — bound to specific model version
// ---------------------------------------------------------------------------
test("Wrong model version — commitment mismatch", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  const tamperedWitness = buildWitness({
    clientId, federationId, roundId,
    modelVersion: 999n,  // ← wrong model version
    privateUpdateCommitment, publicCommitment,
  });

  const satisfied = await checkWitnessSatisfied(tamperedWitness);
  assert.strictEqual(satisfied, false, "Wrong model version should fail");
});

// ---------------------------------------------------------------------------
// Test 6: Tampered public commitment — proof is forgery
// ---------------------------------------------------------------------------
test("Tampered public commitment — forgery detected", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  // Attacker tampers the claimed public commitment
  const fakePubCommitment = (BigInt(publicCommitment) + 1n).toString();

  const tamperedWitness = buildWitness({
    clientId, federationId, roundId, modelVersion,
    privateUpdateCommitment,
    publicCommitment: fakePubCommitment,  // ← tampered
  });

  const satisfied = await checkWitnessSatisfied(tamperedWitness);
  assert.strictEqual(satisfied, false, "Forged commitment should fail");
});

// ---------------------------------------------------------------------------
// Test 7: Proof metadata extraction — no private data included
// ---------------------------------------------------------------------------
test("Proof metadata does not leak private data", async () => {
  const clientId = 1001n;
  const federationId = 42n;
  const roundId = 3n;
  const modelVersion = 7n;
  const privateUpdateCommitment = 0xdeadbeefcafen;

  const publicCommitment = await computeCommitment({ clientId, federationId, roundId, modelVersion, privateUpdateCommitment });

  // Simulate a minimal proof object (as would be returned by groth16.fullProve)
  const fakeProof = { pi_a: ["1", "2"], pi_b: [["3", "4"]], pi_c: ["5", "6"], protocol: "groth16", curve: "bn128" };

  const metadata = extractProofMetadata({
    proof: fakeProof,
    publicSignals: [publicCommitment.toString()],
    publicCommitment,
    clientId, federationId, roundId, modelVersion,
  });

  // Assert: private commitment must NOT appear
  const metadataStr = JSON.stringify(metadata);
  assert.ok(!metadataStr.includes(privateUpdateCommitment.toString(16)), "Private commitment must not appear in metadata");
  assert.ok(!metadataStr.includes(privateUpdateCommitment.toString(10)), "Private commitment must not appear in metadata");

  // Assert: public fields are present
  assert.ok(metadata.publicCommitment, "publicCommitment should be present");
  assert.strictEqual(metadata.clientId, clientId.toString(), "clientId should be present");
  assert.strictEqual(metadata.roundId, roundId.toString(), "roundId should be present");

  console.log(`  Metadata keys: ${Object.keys(metadata).join(", ")}`);
});

// ---------------------------------------------------------------------------
// Test 8: Commitment uniqueness — different rounds produce different commitments
// ---------------------------------------------------------------------------
test("Different rounds produce different commitments", async () => {
  const base = { clientId: 1001n, federationId: 42n, modelVersion: 7n, privateUpdateCommitment: 0x123456n };

  const c1 = await computeCommitment({ ...base, roundId: 1n });
  const c2 = await computeCommitment({ ...base, roundId: 2n });
  const c3 = await computeCommitment({ ...base, roundId: 3n });

  assert.notStrictEqual(c1, c2, "Round 1 and 2 commitments must differ");
  assert.notStrictEqual(c2, c3, "Round 2 and 3 commitments must differ");
  assert.notStrictEqual(c1, c3, "Round 1 and 3 commitments must differ");
  console.log(`  c1=${c1.slice(0,16)}... c2=${c2.slice(0,16)}... c3=${c3.slice(0,16)}...`);
});

// ===========================================================================
// Runner
// ===========================================================================

async function runAll() {
  console.log("\n=== TrustFL ZKP Test Suite ===\n");
  for (const { name, fn } of tests) {
    process.stdout.write(`  [TEST] ${name} ... `);
    try {
      await fn();
      console.log("PASS");
      passed++;
    } catch (err) {
      console.log(`FAIL: ${err.message}`);
      failed++;
    }
  }
  console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
  if (failed > 0) process.exit(1);
}

runAll();
