"""asmr_works 加 main_cover_url（源站大图，详情弹窗用）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6d8e0a2c4b6"
down_revision = "f4c6e8a0d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asmr_works",
        sa.Column("main_cover_url", sa.String(length=1000), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("asmr_works", "main_cover_url")
