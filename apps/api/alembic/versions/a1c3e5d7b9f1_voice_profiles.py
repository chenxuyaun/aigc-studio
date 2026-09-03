"""voice_profiles + voice_corpus：Personal Voice Engine 文风档案与个人语料。

revision: a1c3e5d7b9f1
down_revision: e5f7a9b1d3c5（community_posts，2026-09-03 文件图单头核实）
"""

from alembic import op
import sqlalchemy as sa

revision = "a1c3e5d7b9f1"
down_revision = "e5f7a9b1d3c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=50), nullable=False, server_default="我的文风"),
        sa.Column("voice_dna", sa.JSON(), nullable=True),
        sa.Column("samples", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="auto", index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_table(
        "voice_corpus",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="chat", index=True),
        sa.Column("text_snippet", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("voice_corpus")
    op.drop_table("voice_profiles")
