"""quick_replies.auto：自动触发标记。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3c6a8b1d9f4"
down_revision = "f2a9d5e7b3c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quick_replies",
        sa.Column("auto", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("quick_replies", "auto")
