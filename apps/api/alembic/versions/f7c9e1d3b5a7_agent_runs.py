"""agent_runs 表：Agent 运行时状态留痕（每次被调度执行的目标/结果/状态）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7c9e1d3b5a7"
down_revision = "f6b8d0e2c4a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("goal", sa.Text(), nullable=False, default=""),
        sa.Column("result", sa.Text(), nullable=False, default=""),
        sa.Column("status", sa.String(length=20), nullable=False, default="done"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
