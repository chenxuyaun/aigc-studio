"""asmr_works 加语言字段：langs（语言数组）+ has_chinese（中文版标记）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6a8c0e2d4b6"
down_revision = "f4b6d8e0a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asmr_works", sa.Column("langs", sa.Text(), nullable=False))
    op.add_column(
        "asmr_works",
        sa.Column("has_chinese", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index("ix_asmr_works_has_chinese", "asmr_works", ["has_chinese"])


def downgrade() -> None:
    op.drop_index("ix_asmr_works_has_chinese", table_name="asmr_works")
    op.drop_column("asmr_works", "has_chinese")
    op.drop_column("asmr_works", "langs")
