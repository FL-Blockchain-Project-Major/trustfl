import { readFileSync } from "fs";
import { VK_PATH, verifyProof } from "./zkp.js";

try {
  const input = JSON.parse(readFileSync(0, "utf8"));
  const valid = await verifyProof({
    proof: input?.proof,
    publicSignals: input?.publicSignals,
  });
  process.stdout.write(JSON.stringify({ valid }));
} catch {
  process.stdout.write(JSON.stringify({ valid: false, reason: "verification_error" }));
  process.exitCode = 1;
}
