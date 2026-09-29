# TrustFL ZKP Subsystem Documentation

## Formal Proof Statement

The TrustFL ZKP layer provides a **Proof of Knowledge of Update Commitment** using the Poseidon hash function.

### What the Proof States

> **A client proves that they know a private scalar `privateUpdateCommitment` such that the Poseidon hash of their public identifiers and this private value equals the publicly committed value.**

Formally, a valid proof demonstrates the existence of a secret `s` such that:

```
Poseidon(clientId, federationId, roundId, modelVersion, s) == publicCommitment
```

where `publicCommitment` is known to the verifier, and `s` is never revealed.

### What the Proof DOES Prove

- The prover possesses a specific private value (`privateUpdateCommitment`) that they committed to.
- The commitment is **bound to a specific client** (via `clientId`).
- The commitment is **bound to a specific federation** (via `federationId`).
- The commitment is **bound to a specific training round** (via `roundId`).
- The commitment is **bound to a specific model version** (via `modelVersion`).
- A replay from a different round will produce a different (invalid) commitment.
- Impersonation by another client will produce a different (invalid) commitment.

### What the Proof DOES NOT Prove

- That the client executed any particular training algorithm (e.g., SGD, FedAvg).
- That the underlying training data was well-formed or private.
- That the model weights are accurate, unbiased, or not poisoned.
- The size or magnitude of the model update.
- That the update contributes constructively to the global model.

---

## Circuit Design

### File: `circuits/update_commitment.circom`

```
Template: UpdateCommitment()

Inputs (public):
  - clientId      : BN128 field element representing the client
  - federationId  : BN128 field element representing the federation
  - roundId       : BN128 field element representing the training round
  - modelVersion  : BN128 field element representing the global model version
  - publicCommitment : The expected Poseidon hash output

Inputs (private):
  - privateUpdateCommitment : The secret scalar the client commits to

Constraints:
  Poseidon(clientId, federationId, roundId, modelVersion, privateUpdateCommitment) === publicCommitment
```

### Hash Function

| Field | Value |
|---|---|
| Hash | **Poseidon** (circuit-native, BN128-friendly) |
| Artifact hash | **SHA-256** (used for off-chain artifact integrity) |
| Reason | Poseidon is dramatically more efficient in R1CS/PLONK circuits than SHA-256 |

---

## Proof Generation & Verification Flow

1. **Client**: Selects `privateUpdateCommitment` (derived from model update).
2. **Client**: Computes `publicCommitment = Poseidon(clientId, federationId, roundId, modelVersion, private)`.
3. **Client**: Generates Groth16 proof using `update_commitment.wasm` + `update_commitment.zkey`.
4. **Client**: Submits `publicCommitment` + proof π to the coordinator.
5. **Coordinator**: Calls `groth16.verify(verificationKey, publicSignals, proof)`.
6. **Coordinator**: On valid proof, submits `publicCommitment` (metadata only) to blockchain.
7. **Blockchain**: Records the commitment without any private data.

---

## On-Chain Commitment (Blockchain Integration)

The following metadata is submitted to `UpdateRegistry.submitUpdate()`:
- `publicCommitment` — the Poseidon hash
- `clientId`
- `federationId`
- `roundId`
- `modelVersion`
- `artifactHash` — SHA-256 of the model weight blob (separate from ZKP)

**Private witness (`privateUpdateCommitment`) is NEVER on-chain.**

---

## Limitations

1. **No Training Integrity**: The proof does not guarantee that a legitimate training process was run. A malicious client can commit to any value.
2. **No Data Privacy Proof**: This is not a proof of differential privacy or data governance.
3. **Trusted Setup**: Groth16 requires a trusted Powers of Tau ceremony. The `build.sh` script uses a local ceremony for development. Production requires a multi-party computation (MPC) ceremony.
4. **Field Size**: All inputs must fit in the BN128 scalar field (~254 bits). Large strings must be hashed first.
