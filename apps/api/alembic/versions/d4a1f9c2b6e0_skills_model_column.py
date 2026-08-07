"""skills 表增加 model 列：技能运行时可指定模型。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4a1f9c2b6e0"
down_revision = "14a7b35ecd23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("skills", "model")
