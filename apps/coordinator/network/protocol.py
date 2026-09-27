"""
Network protocol data structures for TrustFL distributed communication.

All messages are plain dataclasses serialised/deserialised to/from JSON.
No framework dependencies — compatible with any HTTP client/server.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> str:
    return json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj)


def _from_dict(cls, data: Dict[str, Any]):
    """Construct a dataclass from a dict, ignoring unknown keys."""
    known = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@dataclass
class RegisterRequest:
    client_id: str
    capabilities: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegisterRequest":
        return _from_dict(cls, data)


@dataclass
class RegisterResponse:
    accepted: bool
    message: str = ""
    coordinator_version: str = "0.4.0"

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegisterResponse":
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
    def from_dict(cls, data: Dict[str, Any]) -> "HeartbeatRequest":
        return _from_dict(cls, data)


@dataclass
class HeartbeatResponse:
    ok: bool
    server_round: int = 0
    message: str = ""

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeartbeatResponse":
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Round instructions (coordinator → client)
# ---------------------------------------------------------------------------

@dataclass
class RoundInstructionsResponse:
    """Sent when a round is active and the client should train."""
    is_active: bool
    round_id: int = 0
    global_parameters: List[List[float]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoundInstructionsResponse":
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Update submission (client → coordinator)
# ---------------------------------------------------------------------------

@dataclass
class SubmitUpdateRequest:
    client_id: str
    round_id: int
    parameters: List[List[float]]
    num_examples: int
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubmitUpdateRequest":
        return _from_dict(cls, data)


@dataclass
class SubmitUpdateResponse:
    accepted: bool
    message: str = ""

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubmitUpdateResponse":
        return _from_dict(cls, data)


# ---------------------------------------------------------------------------
# Status (health / monitoring)
# ---------------------------------------------------------------------------

@dataclass
class StatusResponse:
    status: str                          # WAITING | ROUND_ACTIVE | DONE
    current_round: int = 0
    num_rounds: int = 0
    active_clients: List[str] = field(default_factory=list)
    round_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StatusResponse":
        return _from_dict(cls, data)
