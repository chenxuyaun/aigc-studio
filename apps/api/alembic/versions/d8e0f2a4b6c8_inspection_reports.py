"""每日巡检报告表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8e0f2a4b6c8"
down_revision = "c6d8e0f2a4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inspection_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("inspection_reports")
