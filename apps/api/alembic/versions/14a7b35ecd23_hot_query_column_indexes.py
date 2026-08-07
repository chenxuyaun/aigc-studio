"""hot query column indexes

Revision ID: 14a7b35ecd23
Revises: 275d089379f9
Create Date: 2026-07-31 17:49:11.392162
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '14a7b35ecd23'
down_revision: str | None = '275d089379f9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_generation_tasks_status", "generation_tasks", ["status"])
    op.create_index("ix_generation_tasks_user_id", "generation_tasks", ["user_id"])
    op.create_index("ix_assets_user_id", "assets", ["user_id"])
    op.create_index("ix_photo_albums_owner_id", "photo_albums", ["owner_id"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_photo_albums_owner_id", table_name="photo_albums")
    op.drop_index("ix_assets_user_id", table_name="assets")
    op.drop_index("ix_generation_tasks_user_id", table_name="generation_tasks")
    op.drop_index("ix_generation_tasks_status", table_name="generation_tasks")
