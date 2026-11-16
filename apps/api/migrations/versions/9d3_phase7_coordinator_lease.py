"""Add database-backed coordinator fencing lease.

Revision ID: 9d3_phase7_coordinator_lease
Revises: 8c2f_phase4_reliability
"""

import sqlalchemy as sa
from alembic import op

revision = "9d3_phase7_coordinator_lease"
down_revision = "8c2f_phase4_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coordinator_leases",
        sa.Column("federation_id", sa.String(length=64), primary_key=True),
        sa.Column("holder_id", sa.String(length=128), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("coordinator_leases")
