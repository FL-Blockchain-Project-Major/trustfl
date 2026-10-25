"""
Distributed client agent for TrustFL.

Connects to a remote coordinator over HTTP, polls for round instructions,
trains locally, and submits updates.  No shared filesystem is required.

Lifecycle per step():
  1. Heartbeat  →  server updates client TTL
  2. GET /round/instructions/<cid>  →  check if round is active
  3. If active: train locally → POST /submit
  4. Sleep poll_interval

Retry logic wraps every HTTP call (max_retries with exponential back-off).
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from packages.crypto.trustfl_crypto.keys import ClientIdentity
from packages.crypto.trustfl_crypto.signer import UpdateSigner

logger = logging.getLogger(__name__)

# After this many consecutive failed status polls, a client that has already
# submitted at least one round will treat the coordinator as "done" and exit.
_UNREACHABLE_EXIT_THRESHOLD = 5

# Type alias for the local training function
TrainFn = Callable[
    [int, list[list[float]], dict[str, Any]],  # round_id, params, config
    tuple,  # (new_params, num_examples, metrics)
]


class DistributedClientAgent:
    """
    HTTP-based client that polls the coordinator and submits FL updates.

    Parameters
    ----------
    client_id : str
    coordinator_url : str
        e.g. "http://127.0.0.1:8100"
    train_fn : TrainFn
        Callable(round_id, global_params, config) → (new_params, n_examples, metrics)
    poll_interval : float
        Seconds between each step() call.
    max_retries : int
    retry_delay : float
    training_timeout_seconds : float
        If training takes longer, the update is dropped.
    ca_bundle : str | None
        Path to custom CA bundle for verifying coordinator TLS certificates.
    """

    def __init__(
        self,
        client_id: str,
        coordinator_url: str,
        train_fn: TrainFn,
        poll_interval: float = 2.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        training_timeout_seconds: float = 300.0,
        connection_timeout_seconds: float = 10.0,
        federation_id: str = "fed-default",
        identity: ClientIdentity | None = None,
        identity_path: str | None = None,
        ca_bundle: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.coordinator_url = coordinator_url.rstrip("/")
        if os.getenv("ENVIRONMENT", "").lower() == "production":
            parsed = urllib.parse.urlparse(self.coordinator_url)
            if parsed.scheme == "http":
                host = parsed.hostname or ""
                if not self._is_loopback(host):
                    raise ValueError(
                        f"Plain HTTP to '{self.coordinator_url}' is refused"
                        " in production. Configure TLS (https://) or use a"
                        " loopback address behind a secure tunnel/proxy."
                    )
        self.train_fn = train_fn
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.training_timeout = training_timeout_seconds
        self.connection_timeout = connection_timeout_seconds
        self.federation_id = federation_id
        self.ca_bundle = (
            ca_bundle or os.getenv("FL_CA_BUNDLE") or os.getenv("COORDINATOR_CA_BUNDLE")
        )
        # Identity is durable by default.  Deployments should override this with
        # FL_IDENTITY_PATH (the Compose services mount a per-client key volume).
        # Keeping the client ID in the path prevents accidental key sharing.
        raw_state_dir = Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
        try:
            raw_state_dir.mkdir(parents=True, exist_ok=True)
            state_base = raw_state_dir
        except OSError:
            state_base = Path("/tmp/trustfl_state")
            state_base.mkdir(parents=True, exist_ok=True)

        default_identity_path = state_base / "trustfl" / "keys" / client_id / "private.pem"
        target_identity_path = Path(identity_path) if identity_path else default_identity_path
        if identity is not None:
            self.identity = identity
        else:
            try:
                self.identity = ClientIdentity.load_or_generate(client_id, target_identity_path)
            except OSError:
                logger.warning(
                    "[%s] Key path %s is not writable; falling back to ephemeral in-memory identity",
                    client_id,
                    target_identity_path,
                )
                self.identity = ClientIdentity.generate(client_id)
        self.signer = UpdateSigner(self.identity, federation_id)
        self.enrollment_token = os.getenv("COORDINATOR_ENROLLMENT_TOKEN", "")

        self._stop_event = threading.Event()
        self._bg_thread: threading.Thread | None = None
        self._registered = False
        self.failed = False

        self.last_round_submitted: int = 0
        self.status = "IDLE"
        # Number of consecutive status-poll failures that trigger an exit once
        # at least one round has been submitted.  When the coordinator shuts
        # down immediately after finishing, clients never see a DONE/ABORTED
        # response, so we infer "federation complete" from persistent
        # unreachability.
        self._consecutive_failures: int = 0

    @property
    def is_registered(self) -> bool:
        return self._registered

    @staticmethod
    def _is_loopback(host: str) -> bool:
        if host.lower() in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def register(self) -> bool:
        """POST /register; returns True on success."""
        nonce = uuid.uuid4().hex
        proof = b"|".join(
            (
                b"trustfl-registration-v1",
                self.client_id.encode(),
                self.identity.public_key_b64.encode(),
                nonce.encode(),
            )
        )
        payload = {
            "client_id": self.client_id,
            "capabilities": {
                "public_key": self.identity.public_key_b64,
                "registration_nonce": nonce,
                "registration_signature": base64.b64encode(self.identity.sign(proof)).decode(),
            },
        }
        resp = self._post("/register", payload)
        if resp and resp.get("accepted"):
            self._registered = True
            logger.info("[%s] Registered with coordinator.", self.client_id)
            return True
        logger.error("[%s] Registration failed: %s", self.client_id, resp)
        return False

    def step(self) -> bool:
        """
        One poll/train cycle.  Returns True if a training update was submitted.
        """
        # 1. Heartbeat
        self._heartbeat()

        # 2. Check if the federation is finished so the client can exit cleanly
        status = self._get_status()
        if status is None:
            # Coordinator unreachable.  If we have already contributed to at
            # least one round, treat persistent unreachability as "federation
            # complete" — the coordinator most likely shut down after the final
            # round without sending a DONE response.
            if self.last_round_submitted > 0:
                self._consecutive_failures += 1
                logger.debug(
                    "[%s] Coordinator unreachable (failure %d/%d).",
                    self.client_id,
                    self._consecutive_failures,
                    _UNREACHABLE_EXIT_THRESHOLD,
                )
                if self._consecutive_failures >= _UNREACHABLE_EXIT_THRESHOLD:
                    logger.info(
                        "[%s] Coordinator has been unreachable for %d consecutive polls "
                        "after submitting round %d — assuming federation complete, exiting.",
                        self.client_id,
                        self._consecutive_failures,
                        self.last_round_submitted,
                    )
                    self._stop_event.set()
            return False
        # Coordinator responded — reset the failure counter.
        self._consecutive_failures = 0
        if status.get("status") in ("DONE", "ABORTED"):
            logger.info(
                "[%s] Federation %s — stopping agent.",
                self.client_id,
                status.get("status"),
            )
            self._stop_event.set()
            return False

        # 3. Fetch instructions
        instructions = self._get_round_instructions()
        if instructions is None:
            return False

        if not instructions.get("is_active", False):
            return False

        round_id = instructions["round_id"]
        if round_id <= self.last_round_submitted:
            # Already trained for this round
            return False

        global_params = instructions.get("global_parameters", [])
        config = instructions.get("config", {})

        # 3. Train with timeout
        result = self._train_with_timeout(round_id, global_params, config)
        if result is None:
            self.status = "FAILED"
            return False

        new_params, n_examples, metrics = result

        # 4. Submit update
        submitted = self._submit_update(
            round_id,
            new_params,
            n_examples,
            metrics,
            str(config.get("model_version", "initial")),
        )
        if submitted:
            self.last_round_submitted = round_id
            self.status = "IDLE"
        return submitted

    def start_background_loop(self, wait_for_registration: bool = True) -> None:
        """
        Register then start a background thread that calls step() in a loop.
        """
        if wait_for_registration:
            for attempt in range(self.max_retries):
                if self.register():
                    break
                backoff = min(self.retry_delay * (2**attempt), 30.0)
                time.sleep(backoff)
            else:
                self.failed = True
                logger.error(
                    "[%s] Could not register after %d attempts; exiting.",
                    self.client_id,
                    self.max_retries,
                )
                # Signal stop so main thread exits
                self._stop_event.set()
                return

        self._bg_thread = threading.Thread(
            target=self._loop, daemon=True, name=f"agent-{self.client_id}"
        )
        self._bg_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._bg_thread:
            self._bg_thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.step()
            except Exception as exc:
                logger.error("[%s] Unhandled error in step: %s", self.client_id, exc)
            self._stop_event.wait(timeout=self.poll_interval)

    def _heartbeat(self) -> None:
        self._post("/heartbeat", {"client_id": self.client_id, "status": self.status})

    def _get_round_instructions(self) -> dict[str, Any] | None:
        return self._get(f"/round/instructions/{self.client_id}")

    def _get_status(self) -> dict[str, Any] | None:
        return self._get("/status")

    def _submit_update(
        self,
        round_id: int,
        params: list[list[float]],
        n_examples: int,
        metrics: dict[str, float],
        model_version: str,
    ) -> bool:
        signed_update = self.signer.sign(
            round_id=round_id,
            model_version=model_version,
            parameters=params,
            num_examples=n_examples,
            metrics=metrics,
        )
        payload = {
            "client_id": self.client_id,
            "round_id": round_id,
            "parameters": params,
            "num_examples": n_examples,
            "metrics": metrics,
            "metadata": signed_update.metadata.to_dict(),
            "signature": signed_update.signature_b64,
        }
        resp = self._post("/submit", payload)
        return bool(resp and resp.get("accepted"))

    def _train_with_timeout(
        self,
        round_id: int,
        global_params: list[list[float]],
        config: dict[str, Any],
    ) -> tuple | None:
        """Run train_fn in a thread; return None if it exceeds training_timeout."""
        result_holder: list[Any] = [None]
        exc_holder: list[Exception | None] = [None]

        def _run() -> None:
            try:
                result_holder[0] = self.train_fn(round_id, global_params, config)
            except Exception as exc:
                exc_holder[0] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=self.training_timeout)
        if t.is_alive():
            logger.warning(
                "[%s] Training timed out after %.1f s", self.client_id, self.training_timeout
            )
            return None
        if exc_holder[0]:
            logger.error("[%s] Training exception: %s", self.client_id, exc_holder[0])
            return None
        return result_holder[0]

    # ------------------------------------------------------------------
    # HTTP helpers with retry
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._request("POST", path, payload)

    def _get(self, path: str) -> dict[str, Any] | None:
        return self._request("GET", path, None)

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        url = self.coordinator_url + path
        data = json.dumps(payload).encode() if payload is not None else None
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        proof = b"|".join(
            (
                b"trustfl-request-v1",
                self.client_id.encode(),
                method.encode(),
                path.encode(),
                timestamp.encode(),
                nonce.encode(),
            )
        )
        headers = {
            "Content-Type": "application/json",
            "X-TrustFL-Client-ID": self.client_id,
            "X-TrustFL-Timestamp": timestamp,
            "X-TrustFL-Nonce": nonce,
            "X-TrustFL-Signature": base64.b64encode(self.identity.sign(proof)).decode(),
        }
        token = self.enrollment_token
        if token:
            headers["Authorization"] = f"Bearer {token}"

        ssl_context = None
        if url.startswith("https://"):
            if self.ca_bundle:
                ssl_context = ssl.create_default_context(cafile=self.ca_bundle)
            else:
                ssl_context = ssl.create_default_context()

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(
                    req, timeout=self.connection_timeout, context=ssl_context
                ) as resp:
                    return json.loads(resp.read())
            except urllib.error.URLError as exc:
                logger.debug(
                    "[%s] %s %s attempt %d failed: %s",
                    self.client_id,
                    method,
                    path,
                    attempt + 1,
                    exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))
            except Exception as exc:
                logger.debug("[%s] Request error: %s", self.client_id, exc)
                break
        return None
