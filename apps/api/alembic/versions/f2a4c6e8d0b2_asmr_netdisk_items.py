"""asmr_netdisk_items 表：网盘资源索引（asmrgay 目录元数据）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a4c6e8d0b2"
down_revision = "f8b0d2e4c6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asmr_netdisk_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=30), nullable=False, index=True),
        sa.Column("path", sa.String(length=500), nullable=False, index=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_dir", sa.Boolean(), nullable=False, server_default="1", index=True),
        sa.Column("modified", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "path", name="uq_asmr_disk_source_path"),
    )


def downgrade() -> None:
    op.drop_table("asmr_netdisk_items")
