"""asset/photo storage_backend

Revision ID: c8f3a12d9e01
Revises: b3c91f0a4e22
Create Date: 2026-07-27 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c8f3a12d9e01"
down_revision: str | None = "b3c91f0a4e22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "storage_backend",
                sa.String(length=32),
                server_default="local",
                nullable=False,
            )
        )
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "storage_backend",
                sa.String(length=32),
                server_default="local",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.drop_column("storage_backend")
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_column("storage_backend")
