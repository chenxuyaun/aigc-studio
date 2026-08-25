"""team_runs 表：Agent 团队协作运行持久化（批10）。

revision: d4e6f8a0c2b4
down_revision: c3d5e7f9a1b2（growth_and_memory，单头核实 2026-08-25）
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e6f8a0c2b4"
down_revision = "c3d5e7f9a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 🔴 MySQL：BLOB/TEXT 列不能有 server_default（曾致 api 建表失败循环重启）；
    # 默认值由 ORM 层 default= 提供。
    op.create_table(
        "team_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planning", index=True),
        sa.Column("members", sa.JSON(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("final_report", sa.Text(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("team_runs")
