"""音乐作品加 chords 列（逐段和弦谱，弹唱/Suno 直接用）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2b4d6e8f0a2"
down_revision = "c1a3e5f7d9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL 不允许 TEXT 带默认值：nullable 列，ORM 层 default="" 保证新行有值
    op.add_column("music_works", sa.Column("chords", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("music_works", "chords")
