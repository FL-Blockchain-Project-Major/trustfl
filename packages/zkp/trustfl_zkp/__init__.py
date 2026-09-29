"""
TrustFL ZKP Python bridge.

Exposes the Poseidon-based commitment scheme and metadata extraction to Python.
Uses the ctypes-free approach: we run the node zkp.js module as a subprocess
so no circomlibjs Python bindings are needed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ZKP_DIR = Path(__file__).parent.parent  # packages/zkp/


def _run_node(script: str) -> str:
    """Run an inline Node.js script via subprocess and return stdout."""
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=script.encode(),
        capture_output=True,
        cwd=ZKP_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Node.js ZKP error:\n{result.stderr.decode()}"
        )
    return result.stdout.decode().strip()


def compute_poseidon_commitment(
    client_id: int,
    federation_id: int,
    round_id: int,
    model_version: int,
    private_commitment: int,
) -> str:
    """
    Compute Poseidon(clientId, federationId, roundId, modelVersion, privateCommitment).
    Returns the field element as a decimal string.
    """
    script = f"""
import {{ computeCommitment }} from "./src/zkp.js";
const r = await computeCommitment({{
  clientId: {client_id}n,
  federationId: {federation_id}n,
  roundId: {round_id}n,
  modelVersion: {model_version}n,
  privateUpdateCommitment: {private_commitment}n,
}});
process.stdout.write(r);
"""
    return _run_node(script)


def verify_commitment(
    client_id: int,
    federation_id: int,
    round_id: int,
    model_version: int,
    private_commitment: int,
    public_commitment: str,
) -> bool:
    """
    Verify that Poseidon(clientId, ..., privateCommitment) == publicCommitment.
    Returns True if valid, False otherwise.
    """
    computed = compute_poseidon_commitment(
        client_id, federation_id, round_id, model_version, private_commitment
    )
    return computed == str(public_commitment)


def build_proof_metadata(
    client_id: int,
    federation_id: int,
    round_id: int,
    model_version: int,
    public_commitment: str,
) -> Dict[str, Any]:
    """
    Build on-chain safe proof metadata dict.
    Private commitment is intentionally excluded.
    """
    return {
        "protocol": "poseidon_commitment_v1",
        "publicCommitment": str(public_commitment),
        "clientId": str(client_id),
        "federationId": str(federation_id),
        "roundId": str(round_id),
        "modelVersion": str(model_version),
    }
