"""mission_lessons 表：创作教训（Reflection 沉淀），后续任务注入避免重犯。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f5a7c9e1d3b5"
down_revision = "e4f6a8c0d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_lessons",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("goal", sa.Text(), nullable=False, default=""),
        sa.Column("lesson", sa.Text(), nullable=False, default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("mission_lessons")
