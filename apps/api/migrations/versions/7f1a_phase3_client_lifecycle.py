"""Add client enrollment lifecycle and key metadata.

Revision ID: 7f1a_phase3_client_lifecycle
Revises: 3c1cda7650c5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f1a_phase3_client_lifecycle"
down_revision: str | Sequence[str] | None = "7b4d1f2e5c8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status_enum = sa.Enum(
        "PENDING", "ACTIVE", "SUSPENDED", "REVOKED", name="clientlifecyclestatus"
    )
    status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "clients",
        sa.Column(
            "lifecycle_status",
            status_enum,
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column("clients", sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("clients", sa.Column("key_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("enrollment_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_clients_enrollment_id", "clients", ["enrollment_id"])
    op.execute(
        "UPDATE clients SET enrolled_at = registered_at "
        "WHERE lifecycle_status = 'ACTIVE' AND enrolled_at IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("uq_clients_enrollment_id", "clients", type_="unique")
    for name in (
        "enrollment_id",
        "suspended_at",
        "revoked_at",
        "enrolled_at",
        "key_expires_at",
        "key_version",
        "lifecycle_status",
    ):
        op.drop_column("clients", name)
    sa.Enum(
        "PENDING", "ACTIVE", "SUSPENDED", "REVOKED", name="clientlifecyclestatus"
    ).drop(op.get_bind(), checkfirst=True)
