"""AgentList 外部目录接入：项目/文章/对比表三张表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c6d8e0f2a4b6"
down_revision = "a5c7d9e1f3a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agentlist_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("github_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("homepage_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("license", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agentlist_projects_name", "agentlist_projects", ["name"], unique=True)
    op.create_table(
        "agentlist_articles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("related_projects", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agentlist_articles_title", "agentlist_articles", ["title"])
    op.create_table(
        "agentlist_comparisons",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("projects", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agentlist_comparisons_title", "agentlist_comparisons", ["title"])


def downgrade() -> None:
    op.drop_index("ix_agentlist_comparisons_title", table_name="agentlist_comparisons")
    op.drop_table("agentlist_comparisons")
    op.drop_index("ix_agentlist_articles_title", table_name="agentlist_articles")
    op.drop_table("agentlist_articles")
    op.drop_index("ix_agentlist_projects_name", table_name="agentlist_projects")
    op.drop_table("agentlist_projects")
