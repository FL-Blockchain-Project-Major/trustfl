"""
Coordinator HTTP server for distributed TrustFL.

The server implements a simple REST-like protocol over plain TCP sockets
using Python's built-in http.server — no framework dependencies.

State machine:
  WAITING      → round has not started yet (< min_clients registered)
  ROUND_ACTIVE → training in progress, clients are submitting updates
  DONE         → all rounds completed

A background monitor thread fires every 0.5 s to:
  • detect round timeouts (aggregate with whatever is available)
  • evict clients that have missed heartbeats
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from packages.crypto.trustfl_crypto.canonical import (
    canonical_artifact_bytes,
    hash_parameters,
)
from packages.crypto.trustfl_crypto.keys import PublicKeyRegistry
from packages.crypto.trustfl_crypto.signer import SignedUpdate
from packages.crypto.trustfl_crypto.verifier import UpdateVerifier

from .protocol import (
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
    SubmitUpdateRequest,
    SubmitUpdateResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FedAvg helper (inline — no external dep)
# ---------------------------------------------------------------------------

def _fedavg(
    updates: list[dict[str, Any]],
) -> list[list[float]]:
    """
    Weighted average of parameter updates.
    Each update: {"parameters": [[...], ...], "num_examples": int}
    """
    if not updates:
        raise ValueError("At least one update is required")
    reference = updates[0]["parameters"]
    if not isinstance(reference, list) or any(not isinstance(layer, list) for layer in reference):
        raise ValueError("Update parameters must be a list of layers")
    for update in updates:
        examples = update.get("num_examples")
        parameters = update.get("parameters")
        if not isinstance(examples, int) or examples <= 0:
            raise ValueError("num_examples must be a positive integer")
        if len(parameters) != len(reference):
            raise ValueError("All updates must have the same number of layers")
        for expected, layer in zip(reference, parameters, strict=True):
            if len(layer) != len(expected):
                raise ValueError("All update layers must have matching shapes")
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in layer):
                raise ValueError("Update parameters must be finite numbers")

    total_examples = sum(u["num_examples"] for u in updates)

    num_layers = len(updates[0]["parameters"])
    aggregated: list[list[float]] = []
    for layer_idx in range(num_layers):
        layer_len = len(updates[0]["parameters"][layer_idx])
        layer_avg = [0.0] * layer_len
        for u in updates:
            weight = u["num_examples"] / total_examples
            for i, v in enumerate(u["parameters"][layer_idx]):
                layer_avg[i] += weight * v
        aggregated.append(layer_avg)
    return aggregated


# ---------------------------------------------------------------------------
# Coordinator state (thread-safe FSM)
# ---------------------------------------------------------------------------

class CoordinatorState:
    """
    Thread-safe state container.

    Rounds are 1-indexed internally:
      current_round == 0      → WAITING (not yet started)
      0 < current_round <= N  → ROUND_ACTIVE
      current_round == N+1    → DONE
    """

    def __init__(
        self,
        min_clients: int = 2,
        num_rounds: int = 3,
        round_timeout_seconds: float = 60.0,
        heartbeat_timeout_seconds: float = 30.0,
        blockchain_client = None,
        require_signatures: bool | None = None,
        storage_client=None,
    ) -> None:
        self.min_clients = min_clients
        self.num_rounds = num_rounds
        self.round_timeout_seconds = round_timeout_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.blockchain_client = blockchain_client
        self.storage_client = storage_client
        self.require_signatures = (
            require_signatures
            if require_signatures is not None
            else os.getenv(
                "COORDINATOR_REQUIRE_SIGNATURES",
                "true" if os.getenv("ENVIRONMENT", "development").lower() == "production" else "false",
            ).lower() == "true"
        )
        self.key_registry = PublicKeyRegistry()
        self.update_verifier = UpdateVerifier(self.key_registry)

        self.lock = threading.Lock()
        self.current_round: int = 0          # 0 = not started
        self.round_start_time: float | None = None
        self.global_parameters: list[list[float]] = []

        # cid → {"status": str, "last_heartbeat": float, "registered_at": float, "pubkey": str}
        self.registered_clients: dict[str, dict[str, Any]] = {}

        # cid → update dict (for the current round)
        self.pending_updates: dict[str, dict[str, Any]] = {}

        # History of completed rounds
        self.round_history: list[dict[str, Any]] = []

        self._done_event = threading.Event()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def active_clients(self) -> list[str]:
        """Clients that are ONLINE (heartbeat OK)."""
        return [
            cid
            for cid, info in self.registered_clients.items()
            if info["status"] != "OFFLINE"
        ]

    def _status_label(self) -> str:
        if self.current_round == 0:
            return "WAITING"
        if self.current_round > self.num_rounds:
            return "DONE"
        return "ROUND_ACTIVE"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_client(self, cid: str, capabilities: dict[str, Any]) -> bool:
        with self.lock:
            if cid not in self.registered_clients:
                pubkey = capabilities.get("pubkey") or capabilities.get("public_key")
                if self.require_signatures and not pubkey:
                    logger.warning("Rejecting client %s without a public key", cid)
                    return False

                # BlockChain logic
                if self.blockchain_client:
                    bc_ok = self.blockchain_client.register_client(cid, pubkey)
                    if not bc_ok:
                        logger.error("Blockchain registration failed for %s", cid)
                        return False

                self.registered_clients[cid] = {
                    "status": "ONLINE",
                    "last_heartbeat": time.time(),
                    "registered_at": time.time(),
                    "capabilities": capabilities,
                    "pubkey": pubkey,
                }
                if pubkey:
                    try:
                        self.key_registry.register(cid, pubkey)
                    except (TypeError, ValueError):
                        logger.warning("Rejecting client %s with an invalid public key", cid)
                        del self.registered_clients[cid]
                        return False
                logger.info("Client registered: %s", cid)
            else:
                # Re-registration after disconnect
                self.registered_clients[cid]["status"] = "ONLINE"
                self.registered_clients[cid]["last_heartbeat"] = time.time()
                logger.info("Client re-registered: %s", cid)
            self._start_next_round_if_ready_locked()
            return True

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self, cid: str, status: str) -> int | None:
        """Update last_heartbeat; return current_round or None if unknown."""
        with self.lock:
            if cid not in self.registered_clients:
                return None
            self.registered_clients[cid]["last_heartbeat"] = time.time()
            self.registered_clients[cid]["status"] = status if status != "OFFLINE" else "ONLINE"
            return self.current_round

    # ------------------------------------------------------------------
    # Round instructions
    # ------------------------------------------------------------------

    def get_round_instructions(self, cid: str) -> dict[str, Any]:
        with self.lock:
            is_active = (
                self.current_round > 0
                and self.current_round <= self.num_rounds
                and cid not in self.pending_updates
            )
            return {
                "is_active": is_active,
                "round_id": self.current_round,
                "global_parameters": self.global_parameters,
                "config": {
                    "round": self.current_round,
                    "model_version": (
                        hash_parameters(self.global_parameters)
                        if self.global_parameters
                        else "initial"
                    ),
                    "local_epochs": 1,
                },
            }

    # ------------------------------------------------------------------
    # Update submission
    # ------------------------------------------------------------------

    def submit_update(
        self,
        cid: str,
        round_id: int,
        parameters: list[list[float]],
        num_examples: int,
        metrics: dict[str, float],
        metadata: dict[str, Any] | None = None,
        signature: str | None = None,
    ) -> bool:
        with self.lock:
            if round_id != self.current_round:
                logger.warning(
                    "Stale update from %s: round %d (current %d)",
                    cid, round_id, self.current_round,
                )
                return False

            update_id = f"update_{cid}_{round_id}"
            try:
                artifact_data = canonical_artifact_bytes(parameters, num_examples, metrics)
                stored_artifact = (
                    self.storage_client.save_artifact(
                        artifact_data, str(self.current_round), round_id, cid, update_id
                    )
                    if self.storage_client else None
                )
            except (TypeError, ValueError, OSError) as exc:
                logger.warning("Rejecting update %s: artifact storage failed: %s", update_id, exc)
                return False
            nonce = metadata["nonce"] if metadata else f"nonce_{update_id}"
            artifact_hash = stored_artifact.sha256_hash if stored_artifact else (
                metadata["artifact_hash"] if metadata else "0x_dummy_hash"
            )
            if metadata and metadata.get("artifact_hash") and stored_artifact:
                if metadata["artifact_hash"] != stored_artifact.sha256:
                    logger.warning("Rejecting update %s: artifact hash mismatch", update_id)
                    return False

            if self.require_signatures:
                if not metadata or not signature:
                    logger.warning("Rejecting unsigned update from %s", cid)
                    return False
                try:
                    signed_update = SignedUpdate.from_dict(
                        {
                            "metadata": metadata,
                            "signature": signature,
                            "parameters": parameters,
                            "num_examples": num_examples,
                            "metrics": metrics,
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    logger.warning("Rejecting malformed signed update from %s", cid)
                    return False
                verification = self.update_verifier.verify(signed_update, cid)
                if not verification.ok:
                    logger.warning(
                        "Rejected update from %s: %s",
                        cid,
                        verification.status.value,
                    )
                    return False

            # Submit to blockchain
            if self.blockchain_client:
                bc_ok = self.blockchain_client.submit_update(update_id, round_id, cid, artifact_hash, nonce)
                if not bc_ok:
                    logger.error("Blockchain submit_update failed for %s", cid)
                    return False

                # We assume signature is valid for this Stage 07 integration to keep it simple,
                # but we'll still call mark_verification_state on-chain.
                bc_ok = self.blockchain_client.mark_verification_state(update_id, True)
                if not bc_ok:
                    logger.error("Blockchain mark_verification_state failed for %s", cid)
                    return False

            self.pending_updates[cid] = {
                "parameters": parameters,
                "num_examples": num_examples,
                "metrics": metrics,
                "update_id": update_id,
                "artifact_uri": stored_artifact.uri if stored_artifact else None,
                "artifact_hash": artifact_hash,
            }
            logger.info(
                "Update received from %s (round %d, %d examples)",
                cid, round_id, num_examples,
            )
            # Aggregate eagerly when all active clients have submitted
            if set(self.pending_updates.keys()) >= set(self.active_clients):
                self._aggregate_round_locked(timed_out=False)
            return True

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self._status_label(),
                "current_round": self.current_round,
                "num_rounds": self.num_rounds,
                "active_clients": list(self.active_clients),
                "round_history": list(self.round_history),
            }

    # ------------------------------------------------------------------
    # Monitor (called by background thread — acquires lock internally)
    # ------------------------------------------------------------------

    def monitor_tick(self) -> None:
        """Called periodically. Evicts dead clients; triggers timeout aggregation."""
        with self.lock:
            now = time.time()
            # Evict clients that have missed heartbeats
            for cid, info in self.registered_clients.items():
                if (
                    info["status"] != "OFFLINE"
                    and now - info["last_heartbeat"] > self.heartbeat_timeout_seconds
                ):
                    info["status"] = "OFFLINE"
                    logger.warning("Client %s marked OFFLINE (heartbeat timeout)", cid)

            # Check round timeout
            if (
                self.current_round > 0
                and self.current_round <= self.num_rounds
                and self.round_start_time is not None
                and now - self.round_start_time > self.round_timeout_seconds
            ):
                logger.warning(
                    "Round %d timed out after %.1f s",
                    self.current_round, now - self.round_start_time,
                )
                self._aggregate_round_locked(timed_out=True)

    # ------------------------------------------------------------------
    # Internal (must be called while holding self.lock)
    # ------------------------------------------------------------------

    def _start_next_round_if_ready_locked(self) -> None:
        """Start round 1 when enough clients have registered."""
        if (
            self.current_round == 0
            and len(self.active_clients) >= self.min_clients
        ):
            self.current_round = 1
            self.round_start_time = time.time()
            if self.require_signatures:
                self.update_verifier.set_round(
                    self.current_round,
                    accepted_model_versions=set(),
                )

            if self.blockchain_client:
                bc_ok = self.blockchain_client.create_round(self.current_round, f"model_v{self.current_round}")
                if not bc_ok:
                    logger.error("Blockchain round 1 creation failed")
                else:
                    self.blockchain_client.activate_round(self.current_round)

            logger.info(
                "Round 1 started with %d clients", len(self.active_clients)
            )

    def _aggregate_round_locked(self, timed_out: bool = False) -> None:
        """Run FedAvg over pending_updates and advance the round counter."""
        updates = list(self.pending_updates.values())
        if updates:
            self.global_parameters = _fedavg(updates)

            if self.blockchain_client:
                for u in updates:
                    update_id = u.get("update_id")
                    if update_id:
                        self.blockchain_client.record_aggregation(update_id)
        else:
            logger.warning("No updates to aggregate for round %d", self.current_round)

        record = {
            "round": self.current_round,
            "num_successful_clients": len(updates),
            "timed_out": timed_out,
            "metrics": _avg_metrics([u["metrics"] for u in updates]),
        }
        self.round_history.append(record)
        logger.info(
            "Round %d aggregated: %d clients, timed_out=%s",
            self.current_round, len(updates), timed_out,
        )

        self._advance_round_locked()

    def _advance_round_locked(self) -> None:
        self.pending_updates.clear()

        # Finalize the current round
        if self.blockchain_client:
            self.blockchain_client.finalize_round(self.current_round, f"model_v{self.current_round+1}")

        self.current_round += 1
        if self.current_round > self.num_rounds:
            logger.info("All %d rounds completed.", self.num_rounds)
            self._done_event.set()
        else:
            self.round_start_time = time.time()
            if self.require_signatures:
                self.update_verifier.set_round(
                    self.current_round,
                    accepted_model_versions={hash_parameters(self.global_parameters)}
                    if self.global_parameters
                    else set(),
                )
            if self.blockchain_client:
                bc_ok = self.blockchain_client.create_round(self.current_round, f"model_v{self.current_round}")
                if not bc_ok:
                    logger.error("Blockchain round %d creation failed", self.current_round)
                else:
                    self.blockchain_client.activate_round(self.current_round)
            logger.info("Round %d started.", self.current_round)

    # ------------------------------------------------------------------
    # Blocking wait
    # ------------------------------------------------------------------

    def wait_until_done(self, timeout: float | None = None) -> bool:
        return self._done_event.wait(timeout=timeout)


def _avg_metrics(metrics_list: list[dict[str, float]]) -> dict[str, float]:
    if not metrics_list:
        return {}
    keys = metrics_list[0].keys()
    return {
        k: sum(m.get(k, 0.0) for m in metrics_list) / len(metrics_list)
        for k in keys
    }


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    MAX_BODY_BYTES = 1_048_576
    """Minimal HTTP handler wired to CoordinatorState."""

    state: CoordinatorState  # injected by server factory

    def log_message(self, fmt: str, *args: Any) -> None:  # suppress access log
        pass

    # ---- routing ----------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/status" or self.path == "/health":
            self._respond_json(200, self.state.get_status())
        elif self.path.startswith("/round/instructions/"):
            cid = self.path.split("/")[-1]
            self._respond_json(200, self.state.get_round_instructions(cid))
        else:
            self._respond_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        data = self._read_body()
        if self.path == "/register":
            req = RegisterRequest.from_dict(data)
            ok = self.state.register_client(req.client_id, req.capabilities)
            resp = RegisterResponse(accepted=ok)
            self._respond_json(200, resp.__dict__)

        elif self.path == "/heartbeat":
            req = HeartbeatRequest.from_dict(data)
            rnd = self.state.heartbeat(req.client_id, req.status)
            if rnd is None:
                self._respond_json(404, {"error": "unknown client"})
            else:
                resp = HeartbeatResponse(ok=True, server_round=rnd)
                self._respond_json(200, resp.__dict__)

        elif self.path == "/submit":
            req = SubmitUpdateRequest.from_dict(data)
            ok = self.state.submit_update(
                req.client_id,
                req.round_id,
                req.parameters,
                req.num_examples,
                req.metrics,
                req.metadata,
                req.signature,
            )
            resp = SubmitUpdateResponse(accepted=ok)
            self._respond_json(200, resp.__dict__)

        else:
            self._respond_json(404, {"error": "not found"})

    # ---- helpers ----------------------------------------------------------

    def _read_body(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            self._respond_json(413, {"error": "chunked request bodies are not supported"})
            raise ValueError("chunked request body rejected")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            self._respond_json(400, {"error": "valid Content-Length is required"})
            raise ValueError("invalid Content-Length")
        length = int(raw_length)
        if length > self.MAX_BODY_BYTES:
            self._respond_json(413, {"error": "request body too large"})
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def _respond_json(self, code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class CoordinatorServer:
    """
    Wraps CoordinatorState + HTTPServer in one convenient object.

    Usage::

        server = CoordinatorServer(host="0.0.0.0", port=8100, min_clients=2)
        server.start()           # non-blocking, returns immediately
        server.state.wait_until_done(timeout=120)
        server.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8100,
        min_clients: int = 2,
        num_rounds: int = 3,
        round_timeout_seconds: float = 60.0,
        heartbeat_timeout_seconds: float = 30.0,
        monitor_interval_seconds: float = 0.5,
        blockchain_client = None,
        require_signatures: bool | None = None,
        storage_client = None,
    ) -> None:
        self.host = host
        self.port = port
        self.monitor_interval = monitor_interval_seconds
        self.blockchain_client = blockchain_client

        self.state = CoordinatorState(
            min_clients=min_clients,
            num_rounds=num_rounds,
            round_timeout_seconds=round_timeout_seconds,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            blockchain_client=self.blockchain_client,
            require_signatures=require_signatures,
            storage_client=storage_client,
        )

        # Build the HTTP server with the state injected via closure
        state = self.state

        class BoundHandler(_Handler):
            pass

        BoundHandler.state = state
        self._httpd = HTTPServer((host, port), BoundHandler)
        self._httpd.timeout = 0.5   # so serve_forever can be interrupted quickly

        self._http_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start HTTP + monitor threads (non-blocking)."""
        self._http_thread = threading.Thread(
            target=self._serve_http, daemon=True, name="coord-http"
        )
        self._http_thread.start()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="coord-monitor"
        )
        self._monitor_thread.start()
        logger.info("CoordinatorServer started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._stop_event.set()
        self._httpd.shutdown()
        if self._http_thread:
            self._http_thread.join(timeout=3)
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        logger.info("CoordinatorServer stopped.")

    # ------------------------------------------------------------------

    def _serve_http(self) -> None:
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            pass

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.state.monitor_tick()
            except Exception as exc:
                logger.error("Monitor error: %s", exc)
            time.sleep(self.monitor_interval)
