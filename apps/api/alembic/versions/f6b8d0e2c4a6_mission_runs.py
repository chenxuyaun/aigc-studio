"""mission_runs 表：任务会话持久化（目标/计划/结果/汇总完整入库，可回看复用）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6b8d0e2c4a6"
down_revision = "f5a7c9e1d3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("goal", sa.Text(), nullable=False, default=""),
        sa.Column("plan", sa.Text(), nullable=False, default="[]"),
        sa.Column("results", sa.Text(), nullable=False, default="[]"),
        sa.Column("summary", sa.String(length=200), nullable=False, default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("mission_runs")
