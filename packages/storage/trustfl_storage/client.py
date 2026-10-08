import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests


@dataclass
class ArtifactMetadata:
    uri: str
    sha256_hash: str
    size: int
    model_version: str
    round_id: int
    client_id: str | None = None  # None for global model
    update_id: str | None = None  # None for global model

class StorageClient(ABC):
    @abstractmethod
    def save_artifact(self, data: bytes, model_version: str, round_id: int, client_id: str | None = None, update_id: str | None = None) -> ArtifactMetadata:
        pass

    @abstractmethod
    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        pass

def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class LocalStorageClient(StorageClient):
    """Local filesystem for development."""
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def save_artifact(self, data: bytes, model_version: str, round_id: int, client_id: str | None = None, update_id: str | None = None) -> ArtifactMetadata:
        sha256_hash = compute_sha256(data)
        size = len(data)

        filename = f"{sha256_hash}.bin"
        filepath = os.path.join(self.base_dir, filename)

        with open(filepath, "wb") as f:
            f.write(data)

        return ArtifactMetadata(
            uri=f"file://{filepath}",
            sha256_hash=sha256_hash,
            size=size,
            model_version=model_version,
            round_id=round_id,
            client_id=client_id,
            update_id=update_id
        )

    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError("Invalid URI for LocalStorageClient")

        filepath = uri[len("file://"):]
        with open(filepath, "rb") as f:
            data = f.read()

        actual_hash = compute_sha256(data)
        if actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch! Expected {expected_hash}, got {actual_hash}")

        return data

class IPFSStorageClient(StorageClient):
    """IPFS-compatible storage for model artifacts."""
    def __init__(self, api_url: str = "http://127.0.0.1:5001"):
        self.api_url = api_url.rstrip("/")

    def save_artifact(self, data: bytes, model_version: str, round_id: int, client_id: str | None = None, update_id: str | None = None) -> ArtifactMetadata:
        sha256_hash = compute_sha256(data)
        size = len(data)

        # IPFS HTTP API: POST /api/v0/add
        files = {
            'file': ('artifact.bin', data, 'application/octet-stream')
        }
        resp = requests.post(f"{self.api_url}/api/v0/add", files=files, timeout=(5, 30))
        resp.raise_for_status()

        result = resp.json()
        cid = result["Hash"]

        return ArtifactMetadata(
            uri=f"ipfs://{cid}",
            sha256_hash=sha256_hash,
            size=size,
            model_version=model_version,
            round_id=round_id,
            client_id=client_id,
            update_id=update_id
        )

    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        if not uri.startswith("ipfs://"):
            raise ValueError("Invalid URI for IPFSStorageClient")

        cid = uri[len("ipfs://"):]

        # IPFS HTTP API: POST /api/v0/cat?arg=<cid>
        resp = requests.post(f"{self.api_url}/api/v0/cat?arg={cid}", timeout=(5, 30))
        resp.raise_for_status()

        data = resp.content
        actual_hash = compute_sha256(data)

        if actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch! Expected {expected_hash}, got {actual_hash}")

        return data
