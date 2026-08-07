"""roleplay_lore_entries 表：角色扮演世界书条目。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7a2b4c8d9f1"
down_revision = "d4a1f9c2b6e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roleplay_lore_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("character_name", sa.String(length=100), nullable=False, index=True),
        sa.Column("keyword", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("roleplay_lore_entries")
