"""serial_schedules.fail_count：连载连续失败计数（>=3 自动暂停）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5c7d9e1f3a5"
down_revision = "a4b6c8d0e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "serial_schedules",
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("serial_schedules", "fail_count")
