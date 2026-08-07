"""asmr_favorites 表：ASMR 作品收藏。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8b0d2e4c6a8"
down_revision = "f6a8c0e2d4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asmr_favorites",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("work_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "work_id", name="uq_asmr_fav_user_work"),
    )


def downgrade() -> None:
    op.drop_table("asmr_favorites")
