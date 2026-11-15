# Zero-Knowledge Proofs

This package contains the independently implemented and tested ZKP runtime.
Coordinator update admission requires a real Groth16 proof and fail-closed
verification. Clients use the same runtime to generate proofs from private
update commitments; the coordinator verifies them before persistence,
aggregation, or blockchain submission.

The circuit proves knowledge of a private commitment whose Poseidon hash is the
public commitment, bound to the client, federation, round, and model version.
It does not prove honest training, gradient correctness, model accuracy, or
privacy.

Compiled proving artifacts (`.zkey`, `.ptau`, `.r1cs`, WASM, and witnesses) are
generated on demand and are never committed. Development and CI may generate
ephemeral artifacts with `npm run build`; production must mount externally
reviewed artifacts and set `ZKP_ARTIFACTS_DIR` explicitly.
