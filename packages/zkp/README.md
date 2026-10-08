# Zero-Knowledge Proofs

This package contains the independently implemented and tested ZKP runtime.
Proof generation and verification are an optional integration boundary: the
coordinator currently enforces signed update metadata and artifact hashes, while
ZKP verification can be enabled by a future coordinator verifier without
replacing the real package tests.

Compiled proving artifacts (`.zkey`, `.ptau`, `.r1cs`, and witnesses) are
generated on demand and are never committed.
