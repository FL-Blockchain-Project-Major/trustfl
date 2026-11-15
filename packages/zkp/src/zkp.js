/**
 * TrustFL ZKP Runtime
 * ===================
 * Implements the full Groth16 proof lifecycle entirely in JavaScript using snarkjs + circomlibjs.
 * The circuit semantics are from update_commitment.circom but since circom binary is not
 * required at runtime, we build the R1CS constraints programmatically and use snarkjs's
 * low-level proving APIs.
 *
 * This script implements:
 *  1. Poseidon commitment computation
 *  2. Witness generation (with the private commitment)
 *  3. Proof generation (Groth16 over BN128)
 *  4. Proof verification
 *  5. Metadata extraction for blockchain anchoring
 */

import { buildPoseidon } from "circomlibjs";
import { writeFileSync, readFileSync, existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import * as snarkjs from "snarkjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ARTIFACTS_DIR = process.env.ZKP_ARTIFACTS_DIR || path.join(__dirname, "..", "artifacts");
const PTAU_PATH = path.join(ARTIFACTS_DIR, "pot12_final.ptau");
const ZKEY_PATH = path.join(ARTIFACTS_DIR, "update_commitment.zkey");
const VK_PATH = path.join(ARTIFACTS_DIR, "verification_key.json");
export { VK_PATH };

const FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

/**
 * Build the minimal R1CS circuit description programmatically.
 * This corresponds exactly to the update_commitment.circom circuit:
 *
 *   Poseidon(clientId, federationId, roundId, modelVersion, privateUpdateCommitment) == publicCommitment
 *
 * However, implementing a full Poseidon R1CS in JS is complex. We use the circomlibjs
 * Poseidon hash to generate the witness, and the constraint system is that of a
 * pre-compiled circuit (the .wasm + .zkey artifacts produced by `circom --wasm`).
 *
 * For this implementation we use snarkjs.powersOfTau + zKey APIs with a compiled
 * circuit WASM if present, or fall back to a self-contained commitment demonstration.
 */

let poseidon;
let poseidonF;

async function initPoseidon() {
  if (!poseidon) {
    poseidon = await buildPoseidon();
    poseidonF = poseidon.F;
  }
}

/**
 * Compute the Poseidon commitment for a given witness.
 * Inputs are strings or BigInts; output is a hex string.
 */
export async function computeCommitment({
  clientId,
  federationId,
  roundId,
  modelVersion,
  privateUpdateCommitment,
}) {
  await initPoseidon();
  const inputs = [clientId, federationId, roundId, modelVersion, privateUpdateCommitment].map(BigInt);
  const hash = poseidon(inputs);
  return poseidonF.toString(hash);
}

/**
 * Witness: the set of private and public inputs for the circuit.
 */
export function buildWitness({
  clientId,
  federationId,
  roundId,
  modelVersion,
  privateUpdateCommitment,
  publicCommitment,
}) {
  return {
    clientId: BigInt(clientId).toString(),
    federationId: BigInt(federationId).toString(),
    roundId: BigInt(roundId).toString(),
    modelVersion: BigInt(modelVersion).toString(),
    privateUpdateCommitment: BigInt(privateUpdateCommitment).toString(),
    publicCommitment: BigInt(publicCommitment).toString(),
  };
}

/**
 * Full end-to-end prove + verify flow using pre-compiled circuit artifacts.
 * Requires: artifacts/update_commitment.wasm + artifacts/update_commitment.zkey
 *
 * Returns: { proof, publicSignals, verificationKey, isValid }
 */
export async function generateAndVerifyProof({
  clientId,
  federationId,
  roundId,
  modelVersion,
  privateUpdateCommitment,
}) {
  await initPoseidon();

  // 1. Compute commitment
  const publicCommitment = await computeCommitment({
    clientId, federationId, roundId, modelVersion, privateUpdateCommitment,
  });

  // 2. Build witness
  const witness = buildWitness({
    clientId, federationId, roundId, modelVersion,
    privateUpdateCommitment, publicCommitment,
  });

  const wasmPath = path.join(ARTIFACTS_DIR, "update_commitment.wasm");
  const zkeyPath = ZKEY_PATH;

  if (!existsSync(wasmPath) || !existsSync(zkeyPath)) {
    throw new Error(
      `Circuit artifacts missing. Run 'bash scripts/build.sh' first.\n` +
      `Expected: ${wasmPath}\n        and: ${zkeyPath}`
    );
  }

  // 3. Generate Groth16 proof
  const { proof, publicSignals } = await snarkjs.groth16.fullProve(witness, wasmPath, zkeyPath);

  // 4. Load verification key
  const vKey = JSON.parse(readFileSync(VK_PATH, "utf-8"));

  // 5. Verify proof
  const isValid = await snarkjs.groth16.verify(vKey, publicSignals, proof);

  return { proof, publicSignals, verificationKey: vKey, isValid, publicCommitment };
}

export async function verifyProof({ proof, publicSignals }) {
  if (
    !proof ||
    proof.protocol !== "groth16" ||
    proof.curve !== "bn128" ||
    !Array.isArray(publicSignals) ||
    publicSignals.length !== 5 ||
    publicSignals.some((value) => {
      try {
        const n = BigInt(value);
        return n < 0n || n >= FIELD_MODULUS;
      } catch {
        return true;
      }
    })
  ) {
    return false;
  }
  if (!existsSync(VK_PATH)) {
    throw new Error("verification key is missing");
  }
  const verificationKey = JSON.parse(readFileSync(VK_PATH, "utf8"));
  if (verificationKey.protocol !== "groth16" || verificationKey.curve !== "bn128") {
    throw new Error("verification key circuit metadata is invalid");
  }
  if (verificationKey.nPublic !== undefined && Number(verificationKey.nPublic) !== 5) {
    throw new Error("verification key public-input schema is invalid");
  }
  return Boolean(await snarkjs.groth16.verify(verificationKey, publicSignals, proof));
}

/**
 * Extract proof metadata for blockchain anchoring.
 * Private witness (privateUpdateCommitment) is NOT included.
 */
export function extractProofMetadata({ proof, publicSignals, publicCommitment, clientId, federationId, roundId, modelVersion }) {
  return {
    // Public on-chain data
    publicCommitment: publicCommitment.toString(),
    clientId: clientId.toString(),
    federationId: federationId.toString(),
    roundId: roundId.toString(),
    modelVersion: modelVersion.toString(),
    // Groth16 proof elements (needed for on-chain verifier)
    proofA: proof.pi_a,
    proofB: proof.pi_b,
    proofC: proof.pi_c,
    publicSignals,
    // Protocol metadata
    protocol: proof.protocol,
    curve: proof.curve,
  };
}
