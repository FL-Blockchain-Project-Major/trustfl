"""
Database session factory.
Supports SQLite (dev) and PostgreSQL (prod) via DATABASE_URL env var.
"""
from __future__ import annotations

import os
from collections.abc import Generator

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


def check_config(_app: FastAPI) -> None:
    """Validate required environment variables at startup.
    Call this in the FastAPI startup event to catch misconfigurations early.
    """
    errors = []
    # Check DATABASE_URL
    db_url = os.getenv("DATABASE_URL", "sqlite:///./trustfl.db")
    if ENVIRONMENT == "production" and db_url.startswith("sqlite"):
        errors.append("Production requires a PostgreSQL DATABASE_URL")
    elif db_url.startswith("sqlite") and db_url == "sqlite:///./trustfl.db":
        # Dev mode: check that SQLite file is writable
        import pathlib
        db_path = pathlib.Path("./trustfl.db")
        if db_path.exists() and not os.access(db_path, os.W_OK):
            errors.append("SQLite database file is not writable")
    elif not db_url.startswith("postgresql"):
        errors.append("DATABASE_URL must use sqlite or postgresql")

    # Check API_SECRET_KEY
    api_key = os.getenv("API_SECRET_KEY", "")
    if ENVIRONMENT == "production" and (
        not api_key or api_key in ("CHANGE_ME_IN_PRODUCTION", "changeme_in_production")
    ):
        errors.append("API_SECRET_KEY is not configured. Set it in .env file.")

    # Check COORDINATOR_PRIVATE_KEY
    coord_key = os.getenv("COORDINATOR_PRIVATE_KEY", "")
    if ENVIRONMENT == "production" and (
        not coord_key or coord_key == "0xYOUR_PRIVATE_KEY_HERE"
    ):
        errors.append("COORDINATOR_PRIVATE_KEY is using placeholder value. Set a real private key in .env.")

    if errors:
        raise RuntimeError("Configuration errors:\n  " + "\n  ".join(errors))
