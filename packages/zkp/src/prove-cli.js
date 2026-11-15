import { readFileSync } from "fs";
import { generateProof } from "./zkp.js";

try {
  const input = JSON.parse(readFileSync(0, "utf8"));
  const result = await generateProof(input);
  process.stdout.write(JSON.stringify({
    proof: result.proof,
    publicSignals: result.publicSignals,
    publicCommitment: result.publicCommitment,
  }));
  process.exit(0);
} catch {
  process.stderr.write("proof generation failed\n");
  process.exitCode = 1;
}
