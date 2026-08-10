"""text_documents 增加 status 列（confirmed/pending：AI 自动写入待确认，确认前不参与检索）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4f6a8c0d2b4"
down_revision = "d3e5f7a1c3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "text_documents",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="confirmed",
        ),
    )


def downgrade() -> None:
    op.drop_column("text_documents", "status")
