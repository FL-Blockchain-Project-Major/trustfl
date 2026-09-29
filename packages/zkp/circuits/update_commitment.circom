pragma circom 2.1.5;

/*
 * TrustFL Update Commitment Circuit
 *
 * FORMAL PROOF STATEMENT
 * ======================
 * This circuit proves that the prover knows a private scalar `privateUpdateCommitment`
 * such that:
 *   Poseidon(clientId, federationId, roundId, modelVersion, privateUpdateCommitment)
 *   == publicCommitment
 *
 * WHAT THE PROOF PROVES:
 *   - The prover possesses a private value (the update commitment) that, when combined
 *     with the public identifiers (client, federation, round, model version) and hashed
 *     with Poseidon, yields the publicly known commitment.
 *   - The client is bound to a specific federation, round, and model version.
 *
 * WHAT THE PROOF DOES NOT PROVE:
 *   - That the update was computed by running any particular training algorithm.
 *   - That the training data was well-formed or from any specific distribution.
 *   - That the model weights are correct or produce any particular accuracy.
 *   - The size or content of the model update (only the commitment is bound).
 *
 * CIRCUIT INPUTS (private unless marked public):
 *   - privateUpdateCommitment: The secret scalar the client commits to (private).
 *   - clientId:    public field element representing the client identifier.
 *   - federationId: public field element representing the federation.
 *   - roundId:     public field element representing the training round.
 *   - modelVersion: public field element representing the model version.
 *   - publicCommitment: The expected Poseidon hash output (public).
 *
 * CIRCUIT OUTPUTS:
 *   - valid: 1 if the commitment opens correctly, 0 otherwise (enforced by constraints).
 */

include "node_modules/circomlib/circuits/poseidon.circom";

template UpdateCommitment() {
    // Public inputs (signals known to verifier)
    signal input clientId;
    signal input federationId;
    signal input roundId;
    signal input modelVersion;
    signal input publicCommitment;

    // Private input (the secret witness, known only to the prover)
    signal input privateUpdateCommitment;

    // --- Compute Poseidon commitment ---
    component poseidon = Poseidon(5);
    poseidon.inputs[0] <== clientId;
    poseidon.inputs[1] <== federationId;
    poseidon.inputs[2] <== roundId;
    poseidon.inputs[3] <== modelVersion;
    poseidon.inputs[4] <== privateUpdateCommitment;

    // --- Enforce: computed hash == publicCommitment ---
    publicCommitment === poseidon.out;
}

component main {public [clientId, federationId, roundId, modelVersion, publicCommitment]} = UpdateCommitment();
