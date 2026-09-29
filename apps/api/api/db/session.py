"""
Database session factory.
Supports SQLite (dev) and PostgreSQL (prod) via DATABASE_URL env var.
"""
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trustfl.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
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
