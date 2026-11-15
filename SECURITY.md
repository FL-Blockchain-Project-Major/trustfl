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

## Client identity lifecycle

Production enrollment is coordinator- and administrator-controlled. API
registration creates a `PENDING` client record, and only the dedicated admin
credential may approve, suspend, revoke, or rotate a client key. The coordinator
requires an allow-listed Ed25519 proof of possession and rejects identities
whose lifecycle is not `ACTIVE`. Public keys are immutable until an explicit
rotation, which requires re-enrollment.

Private keys remain on clients. Production requires an external KMS or secret
manager configuration via `CLIENT_KEY_STORE`; the API stores only public keys
and lifecycle metadata. Legacy single-secret authentication and automatic
enrollment are rejected in production.

## Durable round and blockchain consistency

Round records use guarded `CREATED`/`COLLECTING`/`VALIDATING`/`AGGREGATING`/
`COMMITTING`/`COMPLETED` transitions. Accepted updates are persisted before
external blockchain calls and are immutable for a given round/client pair.
Blockchain work is represented by the database-backed `blockchain_outbox` with
stable idempotency keys, bounded exponential retry, and explicit submission
metadata. RPC failure therefore leaves durable recovery work instead of
silently losing the event.

## Circuit scope and limitations

`packages/zkp/circuits/update_commitment.circom` proves knowledge of a private
scalar whose Poseidon hash matches the public commitment and binds that
commitment to client, federation, round, and model-version fields. It does not
prove honest training, gradient validity, model accuracy, or that model weights
equal the private scalar. Artifact integrity remains a separate SHA-256 and
signature control.
