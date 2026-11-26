"""
YOLO and ML Model Parameter Serialization and Management.

Provides:
- Checkpoint serialization and deserialization (parameter state dicts)
- SHA-256 hash integrity checks
- Parameter vectorization and reconstruction
- Model versioning tracking
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


class ParameterSerialization:
    """
    Handles deterministic serialization and deserialization of model parameters.
    Supports list-of-tensors representation as well as state_dict mappings.
    """

    @staticmethod
    def validate_parameters(parameters: list[list[float]]) -> None:
        """Validate that parameters are a non-empty list of finite float lists."""
        if not isinstance(parameters, list) or not parameters:
            raise ValueError("Parameters must be a non-empty list of layers")
        for idx, layer in enumerate(parameters):
            if not isinstance(layer, list):
                raise ValueError(f"Layer {idx} must be a list of floats")
            for v in layer:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f"Non-finite or invalid parameter value in layer {idx}: {v!r}")

    @staticmethod
    def parameters_to_bytes(parameters: list[list[float]]) -> bytes:
        """Serializes parameter list into deterministic byte sequence."""
        ParameterSerialization.validate_parameters(parameters)
        # Clean rounding to avoid floating point cross-platform drift
        payload = {"parameters": [[round(float(v), 8) for v in layer] for layer in parameters]}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def bytes_to_parameters(data: bytes) -> list[list[float]]:
        """Restores parameter list from serialized bytes."""
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict) or "parameters" not in payload:
            raise ValueError("Corrupted parameter payload: missing 'parameters' key")
        params = payload["parameters"]
        ParameterSerialization.validate_parameters(params)
        return params

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Returns 64-character hex SHA-256 hash."""
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def save_checkpoint(
        cls,
        parameters: list[list[float]],
        output_path: Path | str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Path, str]:
        """
        Saves parameter checkpoint with metadata and returns (file_path, sha256_hash).
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload_bytes = cls.parameters_to_bytes(parameters)
        file_hash = cls.compute_sha256(payload_bytes)

        checkpoint_data = {
            "version": "1.0",
            "sha256": file_hash,
            "metadata": metadata or {},
            "parameters": json.loads(payload_bytes.decode("utf-8"))["parameters"],
        }
        path.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
        return path, file_hash

    @classmethod
    def load_checkpoint(
        cls, checkpoint_path: Path | str
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """
        Loads and verifies parameter checkpoint from disk.
        """
        path = Path(checkpoint_path)
        if not path.is_file():
            raise FileNotFoundError(f"Checkpoint file not found: {path}")

        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)

        if "parameters" not in data:
            raise ValueError(f"Invalid checkpoint format in {path}")

        parameters = data["parameters"]
        cls.validate_parameters(parameters)
        expected_sha = data.get("sha256")
        if expected_sha:
            actual_sha = cls.compute_sha256(cls.parameters_to_bytes(parameters))
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Checkpoint SHA-256 mismatch in {path}: expected {expected_sha}, got {actual_sha}"
                )
        metadata = data.get("metadata", {})
        return parameters, metadata
