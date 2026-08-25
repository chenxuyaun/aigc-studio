"""ai_growth_diary + ai_memory_entries：AI 生命体成长日记与长期记忆（批8+9）。

revision: c3d5e7f9a1b2
down_revision: b1c2d3e4f5a6（chat_sessions，2026-08-25 核实单头）
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d5e7f9a1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_growth_diary",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("session_id", sa.String(length=40), nullable=False, server_default="", index=True),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("lessons", sa.JSON(), nullable=True),
        sa.Column("highlights", sa.JSON(), nullable=True),
        sa.Column("msg_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "ai_memory_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="fact", index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_session_id", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_memory_entries")
    op.drop_table("ai_growth_diary")
