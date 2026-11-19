import { readFileSync } from "fs";
import { VK_PATH, verifyProof } from "./zkp.js";

/**
 * TrustFL ZKP Verification CLI
 *
 * Exit-code semantics:
 *   Exit 0: Proof verification executed to completion.
 *           - Valid proof:   {"valid": true}
 *           - Invalid proof: {"valid": false, "reason": "invalid_proof"}
 *   Exit 1: Operational or syntax error.
 *           - Invalid JSON:  {"valid": false, "reason": "invalid_input"}
 *           - Runtime error: {"valid": false, "reason": "verification_error"}
 */
try {
  let input;
  try {
    input = JSON.parse(readFileSync(0, "utf8"));
  } catch {
    process.stdout.write(JSON.stringify({ valid: false, reason: "invalid_input" }));
    process.exit(1);
  }

  const valid = await verifyProof({
    proof: input?.proof,
    publicSignals: input?.publicSignals,
  });

  if (valid) {
    process.stdout.write(JSON.stringify({ valid: true }));
    process.exit(0);
  } else {
    process.stdout.write(JSON.stringify({ valid: false, reason: "invalid_proof" }));
    process.exit(0);
  }
} catch {
  process.stdout.write(JSON.stringify({ valid: false, reason: "verification_error" }));
  process.exit(1);
}
