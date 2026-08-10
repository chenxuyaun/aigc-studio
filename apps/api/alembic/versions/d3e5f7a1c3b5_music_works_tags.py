"""music_works 增加 tags 列（自动标签：风格/主题/情感，逗号分隔）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d3e5f7a1c3b5"
down_revision = "c2b4d6e8f0a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "music_works",
        sa.Column("tags", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("music_works", "tags")
