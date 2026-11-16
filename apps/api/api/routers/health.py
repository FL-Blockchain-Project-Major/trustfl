import os
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
    return {"status": "ready" if ready else "degraded"}


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
    artifacts = Path(os.getenv("ZKP_ARTIFACTS_DIR", ""))
    return bool(os.getenv("ZKP_VERIFY_COMMAND") and (artifacts / "verification_key.json").is_file())


def _storage_ready() -> bool:
    if os.getenv("STORAGE_BACKEND", "local").lower() == "ipfs":
        return bool(os.getenv("IPFS_API_URL") or os.getenv("IPFS_URL"))
    path = Path(os.getenv("STORAGE_LOCAL_DIR", "/tmp/trustfl-artifacts"))
    return path.exists() or path.parent.exists()
