import os
import time
from pathlib import Path

from fastapi import APIRouter
from trustfl_observability import metrics

from apps.api.api.db.session import engine

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
def health_check():
    return {"status": "ok"}


@router.get("/live")
def liveness():
    return {"status": "ok"}


@router.get("/ready")
def readiness():
    checks = {
        "database": _database_ready(),
        "redis": _redis_ready(),
        "zkp": _zkp_ready(),
        "storage": _storage_ready(),
    }
    ready = all(checks.values())
    metrics.set("trustfl_readiness", 1 if ready else 0)
    _record_operational_gauges()
    return {"status": "ready" if ready else "degraded"}


def _record_operational_gauges() -> None:
    """Emit secret-expiry and backup-freshness gauges for Prometheus alerting."""
    now = time.time()
    raw_expiry = os.getenv("TLS_CERT_EXPIRY_EPOCH") or os.getenv("SECRET_EXPIRY_EPOCH")
    if raw_expiry:
        try:
            metrics.set("trustfl_secret_expiry_seconds", max(0.0, float(raw_expiry) - now))
        except ValueError:
            pass
    backup_dir = os.getenv("BACKUP_DIR")
    if backup_dir and Path(backup_dir).is_dir():
        verified: list[float] = []
        for marker in Path(backup_dir).glob("trustfl-*.dump.enc.verified"):
            archive = Path(str(marker).removesuffix(".verified"))
            manifest = Path(f"{archive}.sha256")
            try:
                recorded = marker.read_text(encoding="utf-8").strip().split()
                if len(recorded) != 2 or not archive.is_file() or not manifest.is_file():
                    continue
                expected = manifest.read_text(encoding="utf-8").strip().split()[0]
                if recorded[1] != expected:
                    continue
                verified.append(marker.stat().st_mtime)
            except (OSError, IndexError):
                continue
        if verified:
            metrics.set("trustfl_backup_age_seconds", max(0.0, now - max(verified)))


def _database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


def _redis_ready() -> bool:
    url = os.getenv("REDIS_URL")
    if not url:
        return os.getenv("ENVIRONMENT", "development").lower() == "development"
    try:
        import redis

        return bool(redis.Redis.from_url(url).ping())
    except Exception:
        return False


def _zkp_ready() -> bool:
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        return True
    artifacts_dir = os.getenv("ZKP_ARTIFACTS_DIR", "").strip()
    verify_cmd = os.getenv("ZKP_VERIFY_COMMAND", "").strip()
    if not artifacts_dir or not verify_cmd:
        return False
    artifacts = Path(artifacts_dir)
    return (artifacts / "verification_key.json").is_file()


def _storage_ready() -> bool:
    if os.getenv("STORAGE_BACKEND", "local").lower() == "ipfs":
        return bool(os.getenv("IPFS_API_URL") or os.getenv("IPFS_URL"))
    path = Path(os.getenv("STORAGE_LOCAL_DIR", "/tmp/trustfl-artifacts"))
    return path.exists() or path.parent.exists()
