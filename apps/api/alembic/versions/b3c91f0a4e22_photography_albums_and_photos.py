"""photography albums and photos

Revision ID: b3c91f0a4e22
Revises: 7a645cc7cd51
Create Date: 2026-07-27 20:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b3c91f0a4e22"
down_revision: str | None = "7a645cc7cd51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_albums",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cover_photo_id", sa.String(length=36), nullable=True),
        sa.Column("style_tags", sa.String(length=500), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "photos",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("album_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["album_id"], ["photo_albums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_photos_album_id"), ["album_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_photos_album_id"))
    op.drop_table("photos")
    op.drop_table("photo_albums")
