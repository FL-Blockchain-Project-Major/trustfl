import hashlib
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


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
    def save_artifact(
        self,
        data: bytes,
        model_version: str,
        round_id: int,
        client_id: str | None = None,
        update_id: str | None = None,
    ) -> ArtifactMetadata:
        pass

    @abstractmethod
    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        pass


def compute_sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


class LocalStorageClient(StorageClient):
    """Local filesystem for development."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def save_artifact(
        self,
        data: bytes,
        model_version: str,
        round_id: int,
        client_id: str | None = None,
        update_id: str | None = None,
    ) -> ArtifactMetadata:
        sha256_hash = compute_sha256(data)
        size = len(data)

        filename = f"{sha256_hash.removeprefix('sha256:')}.bin"
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
            update_id=update_id,
        )

    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError("Invalid URI for LocalStorageClient")

        filepath = uri[len("file://") :]
        with open(filepath, "rb") as f:
            data = f.read()

        actual_hash = compute_sha256(data)
        if actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch! Expected {expected_hash}, got {actual_hash}")

        return data


class IPFSStorageClient(StorageClient):
    """IPFS-compatible storage for model artifacts with pinning & replica failover."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:5001",
        replica_urls: list[str] | None = None,
        pin: bool = True,
    ):
        self.api_url = api_url.rstrip("/")
        if replica_urls is None:
            raw_replicas = os.getenv("IPFS_REPLICA_URLS", "")
            self.replica_urls = [u.strip().rstrip("/") for u in raw_replicas.split(",") if u.strip()]
        else:
            self.replica_urls = [u.strip().rstrip("/") for u in replica_urls if u.strip()]
        self.pin = pin
        self.timeout = (
            float(os.getenv("IPFS_CONNECT_TIMEOUT_SECONDS", "5")),
            float(os.getenv("IPFS_READ_TIMEOUT_SECONDS", "30")),
        )

    def _endpoints(self) -> list[str]:
        seen: list[str] = []
        for url in [self.api_url, *self.replica_urls]:
            if url and url not in seen:
                seen.append(url)
        return seen

    def save_artifact(
        self,
        data: bytes,
        model_version: str,
        round_id: int,
        client_id: str | None = None,
        update_id: str | None = None,
    ) -> ArtifactMetadata:
        sha256_hash = compute_sha256(data)
        size = len(data)
        pin_param = "true" if self.pin else "false"

        cid: str | None = None
        last_exc: Exception | None = None
        primary_used: str | None = None
        for endpoint in self._endpoints():
            try:
                files = {"file": ("artifact.bin", data, "application/octet-stream")}
                resp = requests.post(
                    f"{endpoint}/api/v0/add",
                    params={"pin": pin_param},
                    files=files,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                cid = resp.json()["Hash"]
                primary_used = endpoint
                break
            except Exception as exc:
                logger.warning("IPFS upload failed on %s: %s", endpoint, exc)
                last_exc = exc

        if cid is None:
            assert last_exc is not None
            raise last_exc

        # Replicate and pin onto remaining healthy replicas for node-failure resilience.
        for replica in self._endpoints():
            if replica == primary_used:
                continue
            try:
                files = {"file": ("artifact.bin", data, "application/octet-stream")}
                rep_resp = requests.post(
                    f"{replica}/api/v0/add",
                    params={"pin": "true"},
                    files=files,
                    timeout=self.timeout,
                )
                rep_resp.raise_for_status()
            except Exception as exc:
                logger.warning("IPFS replica pin failed on %s for %s: %s", replica, cid, exc)

        return ArtifactMetadata(
            uri=f"ipfs://{cid}",
            sha256_hash=sha256_hash,
            size=size,
            model_version=model_version,
            round_id=round_id,
            client_id=client_id,
            update_id=update_id,
        )

    def load_artifact(self, uri: str, expected_hash: str) -> bytes:
        if not uri.startswith("ipfs://"):
            raise ValueError("Invalid URI for IPFSStorageClient")

        cid = uri[len("ipfs://") :]
        last_exc: Exception | None = None
        for endpoint in self._endpoints():
            try:
                resp = requests.post(
                    f"{endpoint}/api/v0/cat",
                    params={"arg": cid},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.content
                actual_hash = compute_sha256(data)
                if actual_hash != expected_hash:
                    raise ValueError(
                        f"Hash mismatch! Expected {expected_hash}, got {actual_hash}"
                    )
                return data
            except ValueError:
                raise
            except Exception as exc:
                logger.warning("IPFS fetch failed on %s for %s: %s", endpoint, cid, exc)
                last_exc = exc

        assert last_exc is not None
        raise last_exc
