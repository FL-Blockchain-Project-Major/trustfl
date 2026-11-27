"""Crash-safety and idempotency checks for durable coordinator state."""

import uuid

import pytest

from apps.api.api.db.models import Base, Federation
from apps.api.api.db.session import SessionLocal, engine
from apps.coordinator.persistence import CoordinatorPersistence


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_round_transitions_are_atomic_and_validated():
    persistence = CoordinatorPersistence()
    federation_id = persistence.federation_id
    # Use a unique round number to avoid collisions with any previous DB state.
    round_num = int(uuid.uuid4().hex[:4], 16) % 90000 + 10000
    with SessionLocal() as db:
        db.merge(
            Federation(
                id=federation_id,
                name="phase4-test",
                min_clients=1,
                max_rounds=1,
            )
        )
        db.commit()

    persistence.start_round(round_num, "initial")
    assert persistence.transition_round(round_num, {"COLLECTING"}, "VALIDATING")
    assert persistence.transition_round(round_num, {"VALIDATING"}, "AGGREGATING")
    assert not persistence.transition_round(round_num, {"COLLECTING"}, "COMMITTING")


def test_blockchain_outbox_is_idempotent_and_retries_are_bounded():
    persistence = CoordinatorPersistence()
    event_key = f"phase4:{uuid.uuid4().hex}"
    persistence.enqueue_blockchain_event(
        "ROUND_COMMIT",
        event_key,
        {"round_id": "phase4-round"},
    )
    persistence.enqueue_blockchain_event(
        "ROUND_COMMIT",
        event_key,
        {"round_id": "phase4-round"},
    )

    events = [
        event
        for event in persistence.pending_blockchain_events()
        if event["idempotency_key"] == event_key
    ]
    assert len(events) == 1
    event_id = events[0]["id"]
    for _ in range(8):
        persistence.mark_blockchain_retry(event_id, "rpc unavailable")
    assert not [
        event
        for event in persistence.pending_blockchain_events()
        if event["idempotency_key"] == event_key
    ]
