"""Tests for update status AGGREGATED persistence transition."""

import pytest

from apps.api.api.db.models import Base, Update, UpdateStatus
from apps.api.api.db.session import SessionLocal, engine
from apps.coordinator.persistence import CoordinatorPersistence


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


def test_coordinator_persistence_record_aggregation():
    persistence = CoordinatorPersistence()
    update_id = "test_update_agg_1"
    round_id = f"{persistence.federation_id}_round1"

    with SessionLocal() as db:
        # Create a submitted / verified update
        upd = Update(
            id=update_id,
            round_id=round_id,
            client_id="client_001",
            status=UpdateStatus.VERIFIED,
        )
        db.add(upd)
        db.commit()

    # Call record_aggregation
    persistence.record_aggregation(update_id)

    with SessionLocal() as db:
        saved = db.get(Update, update_id)
        assert saved is not None
        assert saved.status == UpdateStatus.AGGREGATED
