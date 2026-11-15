# TrustFL Security Model

## Mandatory proof verification

In production, every coordinator update must include a Groth16 proof and exactly
five public signals. The coordinator checks the signal schema and binds the
client, federation, round, model version, and public commitment before invoking
the configured verifier. Missing, malformed, mismatched, invalid, unavailable,
or unexpectedly failing verification is rejected before artifact storage,
persistence, aggregation, or blockchain submission.

`COORDINATOR_REQUIRE_ZKP=true` and `ZKP_VERIFY_COMMAND` are mandatory in
production. The verifier command must use the reviewed circuit and verification
key mounted through `ZKP_ARTIFACTS_DIR`; a missing or invalid key fails closed.
Proofs and private witnesses are never written to logs.

## Circuit scope and limitations

`packages/zkp/circuits/update_commitment.circom` proves knowledge of a private
scalar whose Poseidon hash matches the public commitment and binds that
commitment to client, federation, round, and model-version fields. It does not
prove honest training, gradient validity, model accuracy, or that model weights
equal the private scalar. Artifact integrity remains a separate SHA-256 and
signature control.
