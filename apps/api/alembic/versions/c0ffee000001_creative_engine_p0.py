"""创作智能内核 P0 数据基座（docs/creative-engine/10 · P0）。

- story_characters 增加 constitution JSON 列（Character Constitution，03 §2）
- story_states：每项目当前故事状态（05 §1）
- story_state_snapshots：每章状态快照（05 §6，可回滚）
- creative_runs：创作流水线审计（10 §3）
- creative_prompts：Prompt 版本化（10 §4）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c0ffee000001"
down_revision = "f9e2d4c6b8a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # story_characters.constitution（JSON 文本；MySQL TEXT 列不可有 server_default，
    # 默认值由应用层提供：models 层 default="{}"）
    op.add_column(
        "story_characters",
        sa.Column("constitution", sa.Text(), nullable=False),
    )

    op.create_table(
        "story_states",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("updated_chapter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_story_states_user_id", "story_states", ["user_id"])

    op.create_table(
        "story_state_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_story_state_snapshots_project_id", "story_state_snapshots", ["project_id"])
    op.create_index("ix_story_state_snapshots_user_id", "story_state_snapshots", ["user_id"])

    op.create_table(
        "creative_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=True),
        sa.Column("run_type", sa.String(length=32), nullable=False, server_default="chapter"),
        sa.Column("stage", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("agent_role", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("action", sa.String(length=16), nullable=False, server_default="GENERATE"),
        sa.Column("verdict_json", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_creative_runs_project_id", "creative_runs", ["project_id"])
    op.create_index("ix_creative_runs_user_id", "creative_runs", ["user_id"])

    op.create_table(
        "creative_prompts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("prompt_key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_creative_prompts_prompt_key", "creative_prompts", ["prompt_key"])


def downgrade() -> None:
    op.drop_index("ix_creative_prompts_prompt_key", table_name="creative_prompts")
    op.drop_table("creative_prompts")
    op.drop_index("ix_creative_runs_user_id", table_name="creative_runs")
    op.drop_index("ix_creative_runs_project_id", table_name="creative_runs")
    op.drop_table("creative_runs")
    op.drop_index("ix_story_state_snapshots_user_id", table_name="story_state_snapshots")
    op.drop_index("ix_story_state_snapshots_project_id", table_name="story_state_snapshots")
    op.drop_table("story_state_snapshots")
    op.drop_index("ix_story_states_user_id", table_name="story_states")
    op.drop_table("story_states")
    op.drop_column("story_characters", "constitution")
