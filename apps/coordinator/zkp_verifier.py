"""Fail-closed coordinator boundary for Groth16 update proofs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def field_from_text(value: str) -> str:
    import hashlib

    return str(int.from_bytes(hashlib.sha256(value.encode()).digest(), "big") % FIELD_MODULUS)


@dataclass(frozen=True)
class ProofVerificationResult:
    valid: bool
    reason: str = ""


class ZKPVerifier:
    """Validate proof shape and delegate cryptographic verification.

    The command must read one JSON object from stdin and write
    ``{"valid": true}`` or ``{"valid": false, "reason": "..."}`` to stdout.
    No proof material is included in exceptions or logs.
    """

    def __init__(self, command: str | None = None, timeout_seconds: float = 10.0) -> None:
        self.command = command or os.getenv("ZKP_VERIFY_COMMAND", "")
        self.timeout_seconds = timeout_seconds
        if not self.command:
            raise RuntimeError("ZKP_VERIFY_COMMAND is required for mandatory proof verification")

    @staticmethod
    def _valid_public_signals(signals: Any) -> bool:
        if not isinstance(signals, list) or len(signals) != 5:
            return False
        return all(isinstance(value, (str, int)) and not isinstance(value, bool) for value in signals)

    @staticmethod
    def _valid_proof(proof: Any) -> bool:
        if not isinstance(proof, dict) or set(proof) != {"pi_a", "pi_b", "pi_c", "protocol", "curve"}:
            return False
        if proof["protocol"] != "groth16" or proof["curve"] != "bn128":
            return False
        return (
            isinstance(proof["pi_a"], list)
            and len(proof["pi_a"]) >= 2
            and isinstance(proof["pi_b"], list)
            and len(proof["pi_b"]) >= 2
            and isinstance(proof["pi_c"], list)
            and len(proof["pi_c"]) >= 2
            and all(isinstance(item, (str, int)) for item in proof["pi_a"][:2])
            and all(isinstance(item, list) for item in proof["pi_b"][:2])
            and all(len(item) >= 2 for item in proof["pi_b"][:2])
            and all(
                isinstance(value, (str, int))
                for item in proof["pi_b"][:2]
                for value in item[:2]
            )
            and all(isinstance(item, (str, int)) for item in proof["pi_c"][:2])
        )

    def verify(
        self,
        *,
        proof: Any,
        public_signals: Any,
        expected_signals: list[str],
    ) -> ProofVerificationResult:
        if not self._valid_proof(proof) or not self._valid_public_signals(public_signals):
            return ProofVerificationResult(False, "MALFORMED_PROOF")
        normalized = [str(value) for value in public_signals]
        if normalized != expected_signals:
            return ProofVerificationResult(False, "PUBLIC_SIGNALS_MISMATCH")
        request = {"proof": proof, "publicSignals": normalized}
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                return ProofVerificationResult(False, "VERIFIER_UNAVAILABLE")
            result = json.loads(completed.stdout)
            if not isinstance(result, dict) or result.get("valid") is not True:
                return ProofVerificationResult(False, "INVALID_PROOF")
            return ProofVerificationResult(True)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return ProofVerificationResult(False, "VERIFIER_ERROR")
