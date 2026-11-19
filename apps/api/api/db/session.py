"""
Database session factory.
Supports SQLite (dev) and PostgreSQL (prod) via DATABASE_URL env var.
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from trustfl_observability import metrics

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trustfl.db")

# Validate DATABASE_URL format
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgresql"):
    # Validate that psycopg is available for PostgreSQL
    try:
        import psycopg  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "psycopg2/psycopg3 is required for PostgreSQL support. "
            "Install with: pip install psycopg[binary]"
        ) from None
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    connect_args = {}
else:
    raise RuntimeError(
        f"Unsupported DATABASE_URL scheme: {DATABASE_URL!r}. "
        "Use 'sqlite:///./trustfl.db' for dev or 'postgresql://...' for prod."
    )

engine_kwargs: dict[str, Any] = {"connect_args": connect_args, "echo": False}
if DATABASE_URL.startswith("postgresql"):
    engine_kwargs.update({
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", "30.0")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "pool_pre_ping": True,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _connection_opened(_dbapi_connection, _connection_record) -> None:
    metrics.inc("trustfl_db_connections_total", {"event": "opened"})


@event.listens_for(engine, "checkout")
def _connection_checked_out(_dbapi_connection, _connection_record, _connection_proxy) -> None:
    metrics.inc("trustfl_db_pool_checkouts_total")


@event.listens_for(engine, "before_cursor_execute")
def _query_started(_conn, _cursor, _statement, _parameters, context, _executemany) -> None:
    context._trustfl_query_started = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _query_finished(_conn, _cursor, _statement, _parameters, context, _executemany) -> None:
    started = getattr(context, "_trustfl_query_started", None)
    if started is not None:
        metrics.inc("trustfl_db_queries_total")
        metrics.observe("trustfl_db_query_seconds", time.perf_counter() - started)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables (dev/test use). Production uses Alembic migrations."""
    from apps.api.api.db.models import Base

    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        # Development databases may predate the Phase 3 migration. Keep local
        # startup compatible; production schema changes are owned by Alembic.
        columns = {column["name"] for column in inspect(engine).get_columns("clients")}
        additions = {
            "lifecycle_status": "VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'",
            "key_version": "INTEGER NOT NULL DEFAULT 1",
            "key_expires_at": "DATETIME",
            "enrolled_at": "DATETIME",
            "revoked_at": "DATETIME",
            "suspended_at": "DATETIME",
            "enrollment_id": "VARCHAR(128)",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE clients ADD COLUMN {name} {definition}"))


def check_config(_app: FastAPI) -> None:
    """Validate required environment variables at startup.
    Call this in the FastAPI startup event to catch misconfigurations early.
    """
    errors = []
    # Check DATABASE_URL
    db_url = os.getenv("DATABASE_URL", "sqlite:///./trustfl.db")
    if ENVIRONMENT == "production" and db_url.startswith("sqlite"):
        errors.append("Production requires a PostgreSQL DATABASE_URL")
    elif db_url.startswith("sqlite"):
        # Dev mode: any SQLite path is allowed; check that the file is writable
        import pathlib

        db_path = pathlib.Path(db_url.removeprefix("sqlite:///"))
        if db_path.exists() and not os.access(db_path, os.W_OK):
            errors.append("SQLite database file is not writable")
    elif not db_url.startswith("postgresql"):
        errors.append("DATABASE_URL must use sqlite or postgresql")

    if ENVIRONMENT == "production":
        for name in ("API_READ_KEY", "API_WRITE_KEY", "API_ADMIN_KEY"):
            value = os.getenv(name, "")
            if not value or value in ("CHANGE_ME_IN_PRODUCTION", "changeme_in_production"):
                errors.append(f"{name} is not configured. Set it through a secret manager.")
        if os.getenv("COORDINATOR_REQUIRE_ZKP", "true").lower() != "true":
            errors.append("Production requires COORDINATOR_REQUIRE_ZKP=true")
        if not os.getenv("ZKP_VERIFY_COMMAND"):
            errors.append("Production requires ZKP_VERIFY_COMMAND")
        if os.getenv("API_LEGACY_AUTH_COMPAT", "false").lower() == "true":
            errors.append("API_LEGACY_AUTH_COMPAT must be false in production")
        if os.getenv("CLIENT_ENROLLMENT_AUTO_APPROVE", "false").lower() == "true":
            errors.append("CLIENT_ENROLLMENT_AUTO_APPROVE must be false in production")
        if os.getenv("CLIENT_KEY_STORE", "").lower() not in {"kms", "secret_manager"}:
            errors.append("CLIENT_KEY_STORE must be kms or secret_manager in production")
        if not os.getenv("REDIS_URL"):
            errors.append("Production requires REDIS_URL for distributed rate limiting")

    # Check COORDINATOR_PRIVATE_KEY
    coord_key = os.getenv("COORDINATOR_PRIVATE_KEY", "")
    if ENVIRONMENT == "production" and (not coord_key or coord_key == "0xYOUR_PRIVATE_KEY_HERE"):
        errors.append(
            "COORDINATOR_PRIVATE_KEY is using placeholder value. Set a real private key in .env."
        )

    if errors:
        raise RuntimeError("Configuration errors:\n  " + "\n  ".join(errors))
