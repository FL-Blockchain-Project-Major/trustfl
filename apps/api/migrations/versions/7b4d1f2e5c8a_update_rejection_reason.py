"""Persist coordinator rejection reason codes.

Revision ID: 7b4d1f2e5c8a
Revises: 3c1cda7650c5
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b4d1f2e5c8a"
down_revision: str | Sequence[str] | None = "3c1cda7650c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("updates", sa.Column("rejection_reason", sa.String(length=128), nullable=True))
    op.add_column("rounds", sa.Column("recovery_state", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rounds", "recovery_state")
    op.drop_column("updates", "rejection_reason")
