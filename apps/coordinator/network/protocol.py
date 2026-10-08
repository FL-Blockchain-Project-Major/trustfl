"""
Network protocol data structures for TrustFL distributed communication.

All messages are plain dataclasses serialised/deserialised to/from JSON.
No framework dependencies — compatible with any HTTP client/server.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> str:
    return json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj)


def _from_dict(cls, data: dict[str, Any]):
    """Construct a dataclass from a dict, ignoring unknown keys."""
    known = set(cls.__dataclass_fields__)
    return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@dataclass
class RegisterRequest:
    client_id: str
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegisterRequest:
        return _from_dict(cls, data)


@dataclass
class RegisterResponse:
    accepted: bool
    message: str = ""
    coordinator_version: str = "0.4.0"

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegisterResponse:
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

@dataclass
class HeartbeatRequest:
    client_id: str
    status: str = "IDLE"

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatRequest:
        return _from_dict(cls, data)


@dataclass
class HeartbeatResponse:
    ok: bool
    server_round: int = 0
    message: str = ""

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatResponse:
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Round instructions (coordinator → client)
# ---------------------------------------------------------------------------

@dataclass
class RoundInstructionsResponse:
    """Sent when a round is active and the client should train."""
    is_active: bool
    round_id: int = 0
    global_parameters: list[list[float]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoundInstructionsResponse:
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Update submission (client → coordinator)
# ---------------------------------------------------------------------------

@dataclass
class SubmitUpdateRequest:
    client_id: str
    round_id: int
    parameters: list[list[float]]
    num_examples: int
    metrics: dict[str, float] = field(default_factory=dict)

    # Cryptographic fields added in Stage 07
    metadata: dict[str, Any] | None = None
    signature: str | None = None

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubmitUpdateRequest:
        return _from_dict(cls, data)


@dataclass
class SubmitUpdateResponse:
    accepted: bool
    message: str = ""

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubmitUpdateResponse:
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Status (health / monitoring)
# ---------------------------------------------------------------------------

@dataclass
class StatusResponse:
    status: str                          # WAITING | ROUND_ACTIVE | DONE
    current_round: int = 0
    num_rounds: int = 0
    active_clients: list[str] = field(default_factory=list)
    round_history: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatusResponse:
        return _from_dict(cls, data)
