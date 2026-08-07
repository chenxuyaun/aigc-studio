"""ai_call_logs table

Revision ID: 275d089379f9
Revises: 82a0553bd654
Create Date: 2026-07-31 17:04:42.570768
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '275d089379f9'
down_revision: str | None = '82a0553bd654'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_call_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=""),
        # TEXT 列不能有 DEFAULT（MySQL 拒绝）；默认值由 ORM 层 default 保证
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
    )
    op.create_index("ix_ai_call_logs_task_id", "ai_call_logs", ["task_id"])
    op.create_index("ix_ai_call_logs_task_type", "ai_call_logs", ["task_type"])
    op.create_index("ix_ai_call_logs_status", "ai_call_logs", ["status"])
    op.create_index("ix_ai_call_logs_created_at", "ai_call_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_call_logs")
