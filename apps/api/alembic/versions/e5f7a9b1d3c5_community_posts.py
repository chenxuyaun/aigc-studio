"""community_posts 表：社区分享墙（批11）。

revision: e5f7a9b1d3c5
down_revision: d4e6f8a0c2b4（team_runs，单头核实 2026-08-25）
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f7a9b1d3c5"
down_revision = "d4e6f8a0c2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_posts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("author_name", sa.String(length=60), nullable=False, server_default="创作者"),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="text", index=True),
        sa.Column("image_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("likes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("liked_by", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("community_posts")
