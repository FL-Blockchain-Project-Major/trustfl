"""Add durable round states, update idempotency, and blockchain outbox.

Revision ID: 8c2f_phase4_reliability
Revises: 7f1a_phase3_client_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c2f_phase4_reliability"
down_revision: str | Sequence[str] | None = "7f1a_phase3_client_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in ("COLLECTING", "VALIDATING", "COMMITTING", "COMPLETED", "RECOVERY_REQUIRED"):
            op.execute(sa.text(f"ALTER TYPE roundstatus ADD VALUE IF NOT EXISTS '{value}'"))
    op.create_unique_constraint("uq_updates_round_client", "updates", ["round_id", "client_id"])
    op.create_unique_constraint("uq_updates_round_nonce", "updates", ["round_id", "nonce"])
    op.create_table(
        "blockchain_outbox",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_blockchain_outbox_idempotency"),
    )
    op.create_index(
        "ix_outbox_status_next_attempt",
        "blockchain_outbox",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_next_attempt", table_name="blockchain_outbox")
    op.drop_table("blockchain_outbox")
    op.drop_constraint("uq_updates_round_nonce", "updates", type_="unique")
    op.drop_constraint("uq_updates_round_client", "updates", type_="unique")
