"""Story Forge 创作引擎表：story_projects / story_chapters / story_characters / serial_schedules + lore.project_id。

将角色扮演能力升级为内容创作基础设施：
- story_projects：创作项目（story bible），关联角色卡与项目级世界书
- story_chapters：章节（outline 大纲 / content 正文 / status 状态机）
- story_characters：角色在故事中的实例（定位/目标/弧线/当前状态/技能）
- serial_schedules：自动连载调度（beat tick 定时生成）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4b6c8d0e2f4"
down_revision = "e3c6a8b1d9f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("synopsis", sa.Text(), nullable=False),
        sa.Column("genre", sa.String(length=50), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="drafting"
        ),
        sa.Column("character_asset_ids", sa.Text(), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "story_chapters",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("chapter_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("outline", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="outline"),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "story_characters",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("character_asset_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="supporting"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("goals", sa.Text(), nullable=False),
        sa.Column("arc", sa.Text(), nullable=False),
        sa.Column("current_state", sa.Text(), nullable=False),
        sa.Column("skill_ids", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "serial_schedules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chapter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="narrative"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("project_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_roleplay_lore_entries_project_id",
        "roleplay_lore_entries",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_roleplay_lore_entries_project_id", table_name="roleplay_lore_entries")
    op.drop_column("roleplay_lore_entries", "project_id")
    op.drop_table("serial_schedules")
    op.drop_table("story_characters")
    op.drop_table("story_chapters")
    op.drop_table("story_projects")
