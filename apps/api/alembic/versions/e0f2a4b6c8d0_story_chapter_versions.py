"""章节版本历史表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e0f2a4b6c8d0"
down_revision = "d8e0f2a4b6c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_chapter_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_story_chapter_versions_chapter_id", "story_chapter_versions", ["chapter_id"])
    op.create_index("ix_story_chapter_versions_user_id", "story_chapter_versions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_story_chapter_versions_user_id", table_name="story_chapter_versions")
    op.drop_index("ix_story_chapter_versions_chapter_id", table_name="story_chapter_versions")
    op.drop_table("story_chapter_versions")
