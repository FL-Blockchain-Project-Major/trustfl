import os

from apps.api.api.db.models import Base
from apps.api.api.db.session import engine
from apps.coordinator.persistence import CoordinatorPersistence


def test_coordinator_lease_fences_second_holder(monkeypatch):
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("FL_FEDERATION_ID", "phase7-lease")
    first = CoordinatorPersistence()
    second = CoordinatorPersistence()
    first.holder_id = "holder-a"
    second.holder_id = "holder-b"

    assert first.acquire_lease(ttl_seconds=60)
    assert not second.acquire_lease(ttl_seconds=60)

    first.release_lease()
    assert second.acquire_lease(ttl_seconds=60)
    second.release_lease()


def test_backup_scripts_require_explicit_secret_configuration():
    assert os.access("scripts/backup_postgres.sh", os.X_OK)
    assert os.access("scripts/restore_postgres.sh", os.X_OK)
    assert os.access("scripts/verify_backup.sh", os.X_OK)
