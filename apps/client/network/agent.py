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

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from packages.crypto.trustfl_crypto.keys import ClientIdentity
from packages.crypto.trustfl_crypto.signer import UpdateSigner

logger = logging.getLogger(__name__)

# Type alias for the local training function
TrainFn = Callable[
    [int, list[list[float]], dict[str, Any]],   # round_id, params, config
    tuple,                                        # (new_params, num_examples, metrics)
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
    ) -> None:
        self.client_id = client_id
        self.coordinator_url = coordinator_url.rstrip("/")
        self.train_fn = train_fn
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.training_timeout = training_timeout_seconds
        self.connection_timeout = connection_timeout_seconds
        self.federation_id = federation_id
        # Identity is durable by default.  Deployments should override this with
        # FL_IDENTITY_PATH (the Compose services mount a per-client key volume).
        # Keeping the client ID in the path prevents accidental key sharing.
        default_identity_path = (
            Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
            / "trustfl"
            / "keys"
            / client_id
            / "private.pem"
        )
        self.identity = identity or ClientIdentity.load_or_generate(
            client_id,
            Path(identity_path) if identity_path else default_identity_path,
        )
        self.signer = UpdateSigner(self.identity, federation_id)
        self.enrollment_token = os.getenv("COORDINATOR_ENROLLMENT_TOKEN", "")

        self._stop_event = threading.Event()
        self._bg_thread: threading.Thread | None = None
        self._registered = False

        self.last_round_submitted: int = 0
        self.status = "IDLE"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self) -> bool:
        """POST /register; returns True on success."""
        payload = {
            "client_id": self.client_id,
            "capabilities": {"public_key": self.identity.public_key_b64},
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

        # 2. Fetch instructions
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
                time.sleep(self.retry_delay * (2 ** attempt))
            else:
                logger.error("[%s] Could not register; giving up.", self.client_id)
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
        headers = {"Content-Type": "application/json", "X-TrustFL-Client-ID": self.client_id}
        token = self.enrollment_token
        if token:
            headers["Authorization"] = f"Bearer {token}"

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.connection_timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.URLError as exc:
                logger.debug(
                    "[%s] %s %s attempt %d failed: %s",
                    self.client_id, method, path, attempt + 1, exc,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
            except Exception as exc:
                logger.debug("[%s] Request error: %s", self.client_id, exc)
                break
        return None
