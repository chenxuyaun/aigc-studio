"""character_profiles 表：角色原著档案（蒸馏产物）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2b4c6d8e0f2"
down_revision = "f6d8e0a2c4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_profiles",
        sa.Column("asset_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_doc_id", sa.String(length=36), nullable=True),
        sa.Column("book_title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("identity", sa.Text(), nullable=False),
        sa.Column("personality", sa.Text(), nullable=False),
        sa.Column("speech_style", sa.Text(), nullable=False),
        sa.Column("knowledge_bounds", sa.Text(), nullable=False),
        sa.Column("relationships", sa.Text(), nullable=False),
        sa.Column("core_memories", sa.Text(), nullable=False),
        sa.Column("book_chunks", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_character_profiles_user_id", "character_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_character_profiles_user_id", table_name="character_profiles")
    op.drop_table("character_profiles")
