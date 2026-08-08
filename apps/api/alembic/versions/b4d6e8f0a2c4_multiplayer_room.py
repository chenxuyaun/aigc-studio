"""多人同场演出：roleplay_chats 加 is_room（多人房间会话，全员可见可加入）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4d6e8f0a2c4"
down_revision = "a3c5e7d9f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roleplay_chats", sa.Column("is_room", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("roleplay_chats", "is_room")
