"""asmr_works 表：ASMR 聚合库（多来源元数据，source+source_work_id 唯一）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4b6d8e0a2c4"
down_revision = "e0f2a4b6c8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asmr_works",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=30), nullable=False, index=True),
        sa.Column("source_work_id", sa.String(length=100), nullable=False, index=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("circle_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_date", sa.DateTime(), nullable=True, index=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_average", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dl_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nsfw", sa.Boolean(), nullable=False, server_default="1", index=True),
        sa.Column("age_category", sa.String(length=20), nullable=False, server_default="adult"),
        sa.Column("vas", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("has_subtitle", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("cover_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("thumbnail_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_work_id", name="uq_asmr_source_work"),
    )


def downgrade() -> None:
    op.drop_table("asmr_works")
