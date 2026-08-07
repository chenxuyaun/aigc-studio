"""asmr_netdisk_items.size_bytes 改 BIGINT（文件可能超 2GB）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4c6e8a0d2b4"
down_revision = "f2a4c6e8d0b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("asmr_netdisk_items", "size_bytes",
                    existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade() -> None:
    op.alter_column("asmr_netdisk_items", "size_bytes",
                    existing_type=sa.BigInteger(), type_=sa.Integer())
