"""mission_runs 加 parent_run_id：Mission 多轮对话链（延续自哪次会话）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8e1d3b5a7c9"
down_revision = "f7c9e1d3b5a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_runs",
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_mission_runs_parent_run_id", "mission_runs", ["parent_run_id"])


def downgrade() -> None:
    op.drop_index("ix_mission_runs_parent_run_id", table_name="mission_runs")
    op.drop_column("mission_runs", "parent_run_id")
