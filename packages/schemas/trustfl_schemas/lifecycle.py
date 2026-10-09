"""
Training Round Lifecycle State Machine.

Lifecycle transitions:
ROUND_CREATED
    → CLIENT_ASSIGNED
    → CLIENT_TRAINING
    → UPDATE_SUBMITTED
    → UPDATE_VERIFIED
    → AGGREGATED
    → MODEL_PUBLISHED
    → ROUND_FINALIZED

Additional terminal error state:
    → ROUND_FAILED
"""

from enum import StrEnum


class RoundState(StrEnum):
    ROUND_CREATED = "ROUND_CREATED"
    CLIENT_ASSIGNED = "CLIENT_ASSIGNED"
    CLIENT_TRAINING = "CLIENT_TRAINING"
    UPDATE_SUBMITTED = "UPDATE_SUBMITTED"
    UPDATE_VERIFIED = "UPDATE_VERIFIED"
    AGGREGATED = "AGGREGATED"
    MODEL_PUBLISHED = "MODEL_PUBLISHED"
    ROUND_FINALIZED = "ROUND_FINALIZED"
    ROUND_FAILED = "ROUND_FAILED"


# Allowed state transitions graph
VALID_TRANSITIONS: dict[RoundState, set[RoundState]] = {
    RoundState.ROUND_CREATED: {RoundState.CLIENT_ASSIGNED, RoundState.ROUND_FAILED},
    RoundState.CLIENT_ASSIGNED: {RoundState.CLIENT_TRAINING, RoundState.ROUND_FAILED},
    RoundState.CLIENT_TRAINING: {RoundState.UPDATE_SUBMITTED, RoundState.ROUND_FAILED},
    RoundState.UPDATE_SUBMITTED: {RoundState.UPDATE_VERIFIED, RoundState.ROUND_FAILED},
    RoundState.UPDATE_VERIFIED: {RoundState.AGGREGATED, RoundState.ROUND_FAILED},
    RoundState.AGGREGATED: {RoundState.MODEL_PUBLISHED, RoundState.ROUND_FAILED},
    RoundState.MODEL_PUBLISHED: {RoundState.ROUND_FINALIZED, RoundState.ROUND_FAILED},
    RoundState.ROUND_FINALIZED: set(),  # Terminal state
    RoundState.ROUND_FAILED: set(),  # Terminal error state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal lifecycle state transition is attempted."""

    def __init__(
        self, current_state: RoundState, new_state: RoundState, message: str | None = None
    ):
        self.current_state = current_state
        self.new_state = new_state
        msg = (
            message
            or f"Illegal lifecycle transition: cannot move from {current_state.value} to {new_state.value}."
        )
        super().__init__(msg)


def assert_valid_transition(current: RoundState, target: RoundState) -> None:
    """Validate that transition from current state to target state is permissible."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(current, target)
