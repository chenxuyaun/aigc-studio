"""创作目标模式 + 定时创作：creation_goals / scheduled_creations 两张表。

- creation_goals：Goal Mode（目标 → AI 自主拆解执行 → 成果总结）
- scheduled_creations：定时把 prompt 作为生成任务入队（daily / interval）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d0a1b2c3d4e5"
down_revision = "c0ffee000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creation_goals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("goal_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_creation_goals_user_id", "creation_goals", ["user_id"])
    op.create_index("ix_creation_goals_status", "creation_goals", ["status"])

    op.create_table(
        "scheduled_creations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "task_type",
            sa.String(length=20),
            nullable=False,
            server_default="text",
        ),
        sa.Column("schedule_type", sa.String(length=10), nullable=False),
        sa.Column("daily_time", sa.Time(), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result_task_id", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scheduled_creations_user_id", "scheduled_creations", ["user_id"])
    op.create_index(
        "ix_scheduled_creations_next_run_at", "scheduled_creations", ["next_run_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_creations_next_run_at", table_name="scheduled_creations")
    op.drop_index("ix_scheduled_creations_user_id", table_name="scheduled_creations")
    op.drop_table("scheduled_creations")
    op.drop_index("ix_creation_goals_status", table_name="creation_goals")
    op.drop_index("ix_creation_goals_user_id", table_name="creation_goals")
    op.drop_table("creation_goals")
