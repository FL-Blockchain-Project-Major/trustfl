"""
SQLAlchemy ORM models for TrustFL API control plane.
All tables store system metadata only — no weights, no private data.
"""
from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass

def _utcnow():
    return datetime.now(UTC)

class FederationStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"

class RoundStatus(enum.StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    AGGREGATING = "AGGREGATING"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"

class UpdateStatus(enum.StrEnum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    AGGREGATED = "AGGREGATED"
    REJECTED = "REJECTED"

class Federation(Base):
    __tablename__ = "federations"
    id = Column(String(64), primary_key=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(FederationStatus), default=FederationStatus.ACTIVE, nullable=False)
    min_clients = Column(Integer, default=2, nullable=False)
    max_rounds = Column(Integer, default=10, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    clients = relationship("Client", back_populates="federation", cascade="all, delete-orphan")
    rounds = relationship("Round", back_populates="federation", cascade="all, delete-orphan")

class Client(Base):
    __tablename__ = "clients"
    id = Column(String(64), primary_key=True)
    federation_id = Column(String(64), ForeignKey("federations.id", ondelete="CASCADE"), nullable=False)
    public_key_b64 = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    capabilities = Column(Text, nullable=True)  # JSON string
    registered_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    federation = relationship("Federation", back_populates="clients")
    updates = relationship("Update", back_populates="client")
    __table_args__ = (Index("ix_clients_federation_id", "federation_id"),)

class Round(Base):
    __tablename__ = "rounds"
    id = Column(String(64), primary_key=True)  # e.g. "fed1_round3"
    federation_id = Column(String(64), ForeignKey("federations.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    status = Column(SAEnum(RoundStatus), default=RoundStatus.CREATED, nullable=False)
    model_version = Column(String(128), nullable=True)
    global_model_artifact_id = Column(String(128), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    federation = relationship("Federation", back_populates="rounds")
    updates = relationship("Update", back_populates="round")
    __table_args__ = (Index("ix_rounds_federation_id", "federation_id"),)

class Update(Base):
    __tablename__ = "updates"
    id = Column(String(128), primary_key=True)
    round_id = Column(String(64), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    status = Column(SAEnum(UpdateStatus), default=UpdateStatus.SUBMITTED, nullable=False)
    artifact_id = Column(String(128), nullable=True)
    artifact_hash = Column(String(128), nullable=True)
    nonce = Column(String(128), nullable=True)
    num_examples = Column(Integer, nullable=True)
    loss = Column(Float, nullable=True)
    submitted_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    round = relationship("Round", back_populates="updates")
    client = relationship("Client", back_populates="updates")
    __table_args__ = (Index("ix_updates_round_id", "round_id"), Index("ix_updates_client_id", "client_id"),)

class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id = Column(String(128), primary_key=True)
    federation_id = Column(String(64), nullable=False)
    round_number = Column(Integer, nullable=True)
    client_id = Column(String(64), nullable=True)  # None = global model
    uri = Column(Text, nullable=False)
    sha256_hash = Column(String(128), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    model_version = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (Index("ix_artifacts_federation_id", "federation_id"),)

class Proof(Base):
    __tablename__ = "proofs"
    id = Column(String(128), primary_key=True)
    update_id = Column(String(128), ForeignKey("updates.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(String(64), nullable=False)
    federation_id = Column(String(64), nullable=False)
    round_id = Column(String(64), nullable=False)
    model_version = Column(String(128), nullable=True)
    public_commitment = Column(Text, nullable=False)
    protocol = Column(String(64), default="poseidon_commitment_v1", nullable=False)
    is_valid = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    __table_args__ = (Index("ix_proofs_update_id", "update_id"),)

class BlockchainTransaction(Base):
    __tablename__ = "blockchain_transactions"
    id = Column(String(128), primary_key=True)
    tx_hash = Column(String(128), nullable=True)
    contract_name = Column(String(64), nullable=False)
    function_name = Column(String(64), nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)  # PENDING, CONFIRMED, FAILED
    entity_id = Column(String(128), nullable=True)  # reference to client/round/update ID
    entity_type = Column(String(32), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_bctx_entity_id", "entity_id"),)
