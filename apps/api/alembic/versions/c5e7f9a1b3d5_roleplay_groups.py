"""完整群功能：roleplay_groups（群资料/邀请码）+ roleplay_group_members（成员）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5e7f9a1b3d5"
down_revision = "b4d6e8f0a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roleplay_groups",
        sa.Column("chat_id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("invite_code", sa.String(length=12), nullable=False, index=True, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_table(
        "roleplay_group_members",
        sa.Column("group_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("roleplay_group_members")
    op.drop_table("roleplay_groups")
