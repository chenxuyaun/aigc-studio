"""多人创作共享：角色卡 / 世界书 / 正则脚本加 is_shared 标记（admin 共享，全员可见可用）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3c5e7d9f1b3"
down_revision = "a2b4c6d8e0f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roleplay_characters", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("roleplay_lore_entries", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("regex_scripts", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("roleplay_characters", "is_shared")
    op.drop_column("roleplay_lore_entries", "is_shared")
    op.drop_column("regex_scripts", "is_shared")
