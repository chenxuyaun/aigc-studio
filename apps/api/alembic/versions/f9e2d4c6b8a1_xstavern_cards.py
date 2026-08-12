"""xstavern_cards 表：外部角色卡市场公开索引（只读浏览）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f9e2d4c6b8a1"
down_revision = "f8e1d3b5a7c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "xstavern_cards",
        sa.Column("slug", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("author", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=60), nullable=False, server_default="", index=True),
        # MySQL 不允许 TEXT 列设 server_default
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("nsfw", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("preview_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("xstavern_cards")
