"""P3 deprecation：下线 provider_configs 表（供应商管理已迁至模型中心）。

deprecation-plan.md P3：
- generation_tasks.provider_id 解除外键并置空（保留列作历史痕迹）
- DROP TABLE provider_configs
- 回滚：结构可由 downgrade 重建，数据需用删除前的 mysqldump 恢复
  （部署前备份：server ~/backups-pre-p3/provider_configs.sql）

revision = "a7b9c1d3e5f7"
down_revision = "d0a1b2c3d4e5"
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7b9c1d3e5f7"
down_revision = "d0a1b2c3d4e5"
branch_labels = None
depends_on = None


def _provider_fk_names() -> list[str]:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'generation_tasks' "
            "AND COLUMN_NAME = 'provider_id' AND REFERENCED_TABLE_NAME = 'provider_configs'"
        )
    ).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    for name in _provider_fk_names():
        op.drop_constraint(name, "generation_tasks", type_="foreignkey")
    op.execute("UPDATE generation_tasks SET provider_id = NULL WHERE provider_id IS NOT NULL")
    op.drop_table("provider_configs")


def downgrade() -> None:
    """仅重建结构（与 aacdd5c588d7 初版一致）；历史数据须从 mysqldump 恢复。"""
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("default_model", sa.String(length=100), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_generation_tasks_provider_id",
        "generation_tasks",
        "provider_configs",
        ["provider_id"],
        ["id"],
    )
