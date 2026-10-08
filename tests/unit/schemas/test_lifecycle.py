"""
Unit tests for TrustFL training round lifecycle transitions.
"""

import unittest

from trustfl_schemas.lifecycle import (
    InvalidStateTransitionError,
    RoundState,
)
from trustfl_schemas.models import TrainingRound


class TestLifecycle(unittest.TestCase):
    def test_valid_sequential_lifecycle_progression(self) -> None:
        round_obj = TrainingRound(
            round_id="rnd_0001",
            federation_id="fed_0001",
            round_number=1,
            base_model_version_id="mod_base_v1",
        )
        self.assertEqual(round_obj.state, RoundState.ROUND_CREATED)

        # Progression sequence:
        # ROUND_CREATED -> CLIENT_ASSIGNED -> CLIENT_TRAINING -> UPDATE_SUBMITTED
        # -> UPDATE_VERIFIED -> AGGREGATED -> MODEL_PUBLISHED -> ROUND_FINALIZED
        transitions = [
            RoundState.CLIENT_ASSIGNED,
            RoundState.CLIENT_TRAINING,
            RoundState.UPDATE_SUBMITTED,
            RoundState.UPDATE_VERIFIED,
            RoundState.AGGREGATED,
            RoundState.MODEL_PUBLISHED,
            RoundState.ROUND_FINALIZED,
        ]

        for next_state in transitions:
            round_obj.transition_to(next_state)
            self.assertEqual(round_obj.state, next_state)

    def test_invalid_lifecycle_skipping(self) -> None:
        round_obj = TrainingRound(
            round_id="rnd_0001",
            federation_id="fed_0001",
            round_number=1,
            base_model_version_id="mod_base_v1",
        )
        # Attempting to jump directly from ROUND_CREATED to AGGREGATED
        with self.assertRaises(InvalidStateTransitionError):
            round_obj.transition_to(RoundState.AGGREGATED)

        # Attempting to jump from ROUND_CREATED directly to ROUND_FINALIZED
        with self.assertRaises(InvalidStateTransitionError):
            round_obj.transition_to(RoundState.ROUND_FINALIZED)

    def test_terminal_state_cannot_transition(self) -> None:
        round_obj = TrainingRound(
            round_id="rnd_0001",
            federation_id="fed_0001",
            round_number=1,
            base_model_version_id="mod_base_v1",
        )
        round_obj.state = RoundState.ROUND_FINALIZED

        with self.assertRaises(InvalidStateTransitionError):
            round_obj.transition_to(RoundState.ROUND_CREATED)

        round_obj.state = RoundState.ROUND_FAILED
        with self.assertRaises(InvalidStateTransitionError):
            round_obj.transition_to(RoundState.CLIENT_ASSIGNED)

    def test_transition_to_failed_state_allowed(self) -> None:
        for state in [
            RoundState.ROUND_CREATED,
            RoundState.CLIENT_ASSIGNED,
            RoundState.CLIENT_TRAINING,
            RoundState.UPDATE_SUBMITTED,
            RoundState.UPDATE_VERIFIED,
            RoundState.AGGREGATED,
            RoundState.MODEL_PUBLISHED,
        ]:
            round_obj = TrainingRound(
                round_id="rnd_0001",
                federation_id="fed_0001",
                round_number=1,
                base_model_version_id="mod_base_v1",
            )
            round_obj.state = state
            round_obj.transition_to(RoundState.ROUND_FAILED)
            self.assertEqual(round_obj.state, RoundState.ROUND_FAILED)


if __name__ == "__main__":
    unittest.main()
