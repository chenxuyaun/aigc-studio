"""音乐作品：music_works 表（圆桌/写歌定稿的创作资产）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1a3e5f7d9b1"
down_revision = "c5e7f9a1b3d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "music_works",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("title", sa.String(100), nullable=False, server_default=""),
        sa.Column("theme", sa.String(500), nullable=False, server_default=""),
        sa.Column("style", sa.String(100), nullable=False, server_default=""),
        sa.Column("lyrics", sa.Text(), nullable=False),
        sa.Column("arrangement", sa.Text(), nullable=False),
        sa.Column("style_en", sa.Text(), nullable=False),
        sa.Column("rounds", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="roundtable"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("music_works")
