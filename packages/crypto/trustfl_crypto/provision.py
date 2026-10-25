"""
Client identity provisioning and dynamic slot claiming for TrustFL.

Provides utilities for:
1. Validating client count configurations (FL_MIN_CLIENTS <= FL_NUM_CLIENTS).
2. Generating stable, persistent per-client Ed25519 identities.
3. Writing coordinator allowlist mappings (COORDINATOR_ENROLLMENT_ALLOWLIST).
4. Atomically claiming unique client identity slots in container replicas via POSIX locks.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .keys import ClientIdentity

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger("trustfl.crypto.provision")


def validate_client_counts(
    num_clients: int,
    min_clients: int | None = None,
) -> tuple[int, int]:
    """
    Validate configured client counts for a single-host deployment.

    Enforces:
    - num_clients >= 1
    - min_clients >= 1 (if specified)
    - min_clients <= num_clients (quorum cannot exceed configured workers)

    Raises:
        ValueError: If client counts violate single-host topology constraints.
    """
    if not isinstance(num_clients, int) or isinstance(num_clients, bool) or num_clients < 1:
        raise ValueError(
            f"Invalid configuration: FL_NUM_CLIENTS must be an integer >= 1 (got {num_clients!r})."
        )

    resolved_min = min_clients if min_clients is not None else num_clients
    if not isinstance(resolved_min, int) or isinstance(resolved_min, bool) or resolved_min < 1:
        raise ValueError(
            f"Invalid configuration: FL_MIN_CLIENTS must be an integer >= 1 (got {min_clients!r})."
        )

    if resolved_min > num_clients:
        raise ValueError(
            f"Invalid quorum configuration: FL_MIN_CLIENTS ({resolved_min}) cannot exceed "
            f"FL_NUM_CLIENTS ({num_clients}) in a single-host deployment where all workers "
            "are expected to participate."
        )

    return num_clients, resolved_min


def provision_client_identities(
    keys_dir: Path | str,
    num_clients: int,
    min_clients: int | None = None,
    base_client_id: str = "client",
) -> dict[str, str]:
    """
    Provision persistent signing identities for num_clients workers and write allowlist.json.

    For each client slot client_001 .. client_{num_clients:03d}:
    - Loads existing Ed25519 private key from <keys_dir>/<client_id>/private.pem if present.
    - Generates a fresh Ed25519 private key and writes it with 0600 permissions if not present.
    - Gathers base64 public key for coordinator enrollment allowlisting.
    - Writes <keys_dir>/allowlist.json atomically with 0644 permissions.

    Returns:
        Dictionary mapping client_id to base64 public key.
    """
    num_c, _ = validate_client_counts(num_clients, min_clients)
    root = Path(keys_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    allowlist: dict[str, str] = {}
    for i in range(1, num_c + 1):
        cid = f"{base_client_id}_{i:03d}"
        client_dir = root / cid
        client_dir.mkdir(parents=True, exist_ok=True)
        key_file = client_dir / "private.pem"

        identity = ClientIdentity.load_or_generate(cid, key_file)
        allowlist[cid] = identity.public_key_b64

    # Atomic write to allowlist.json
    allowlist_file = root / "allowlist.json"
    tmp_file = root / f".allowlist.{uuid.uuid4().hex}.tmp"
    tmp_file.write_text(json.dumps(allowlist, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp_file, 0o644)
    except OSError:
        pass
    tmp_file.replace(allowlist_file)

    logger.info(
        "Provisioned %d persistent client identities in %s; wrote allowlist to %s",
        num_c,
        root,
        allowlist_file,
    )
    return allowlist


def claim_client_identity(
    keys_dir: Path | str,
    num_clients: int = 2,
    base_client_id: str = "client",
) -> tuple[str, ClientIdentity, Any]:
    """
    Atomically claim an available client identity slot using a POSIX file lock.

    Iterates through client_001 .. client_{num_clients:03d}, attempting to acquire
    an exclusive non-blocking lock. The returned file handle MUST be kept open by
    the caller for the process lifetime so the lock remains active.

    Returns:
        tuple of (client_id, ClientIdentity, lock_file_handle)

    Raises:
        RuntimeError: If all client identity slots are locked by other running workers.
    """
    if num_clients < 1:
        raise ValueError(f"num_clients must be >= 1 (got {num_clients})")

    keys_path = Path(keys_dir).resolve()
    keys_path.mkdir(parents=True, exist_ok=True)

    for i in range(1, num_clients + 1):
        cid = f"{base_client_id}_{i:03d}"
        client_dir = keys_path / cid
        client_dir.mkdir(parents=True, exist_ok=True)
        lock_file = client_dir / ".lock"

        try:
            f = open(lock_file, "a+", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            key_file = client_dir / "private.pem"
            identity = ClientIdentity.load_or_generate(cid, key_file)
            logger.info("Worker successfully claimed identity %s (lock held on %s)", cid, lock_file)
            return cid, identity, f
        except (BlockingIOError, OSError) as exc:
            logger.debug("Slot %s unavailable (%s); checking next slot.", cid, exc)
            continue

    raise RuntimeError(
        f"Unable to claim client identity: all {num_clients} client identity slots "
        f"in {keys_path} are currently in use by other running workers."
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    parser = argparse.ArgumentParser(description="TrustFL Client Identity Provisioner")
    parser.add_argument(
        "--keys-dir",
        default=os.environ.get("FL_KEYS_DIR", "/var/lib/trustfl/keys"),
        help="Directory to store persistent per-client keys and allowlist.json",
    )
    parser.add_argument(
        "--num-clients",
        type=int,
        default=int(os.environ.get("FL_NUM_CLIENTS", 2)),
        help="Number of client workers to provision",
    )
    parser.add_argument(
        "--min-clients",
        type=int,
        default=int(os.environ.get("FL_MIN_CLIENTS", 2)),
        help="Minimum required clients for federation quorum",
    )
    args = parser.parse_args()

    try:
        allowlist = provision_client_identities(
            keys_dir=args.keys_dir,
            num_clients=args.num_clients,
            min_clients=args.min_clients,
        )
        print(f"Successfully provisioned {len(allowlist)} client identities:")
        for cid, pub in allowlist.items():
            print(f"  {cid}: {pub}")
    except ValueError as exc:
        logger.error("Configuration validation failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

