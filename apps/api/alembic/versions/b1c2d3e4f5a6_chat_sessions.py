"""chat_sessions 表：AI 调度大厅会话上云（saiOS v2 P1）。

revision: b1c2d3e4f5a6
down_revision: a7b9c1d3e5f7（服务器实际 head，2026-08-24 核实单头一致）
"""

from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a7b9c1d3e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False, server_default="新会话"),
        sa.Column("session_group", sa.String(length=60), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        # MySQL JSON 列；空数组默认
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_chat_sessions_user_updated",
        "chat_sessions",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")
