"""SillyTavern 功能融入：角色卡/会话/世界书扩展/正则/快捷回复/persona 表。

- roleplay_characters: 角色卡结构化字段（asset_id 主键，与 assets 一一对应）
- roleplay_chats: 服务端会话（messages JSON 字符串）
- roleplay_lore_entries: 扩展世界书字段（keywords/constant/selective/position/order/depth/概率等），character_name 改可空
- regex_scripts / quick_replies / roleplay_personas: 正则脚本/快捷回复/用户形象
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a9d5e7b3c1"
down_revision = "e7a2b4c8d9f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 角色卡结构化表
    op.create_table(
        "roleplay_characters",
        sa.Column("asset_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("personality", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("first_mes", sa.Text(), nullable=False),
        sa.Column("mes_example", sa.Text(), nullable=False),
        sa.Column("alternate_greetings", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("post_history_instructions", sa.Text(), nullable=False),
        sa.Column("creator_notes", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("character_book", sa.Text(), nullable=False),
        sa.Column("talkativeness", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("depth_prompt", sa.Text(), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 服务端会话
    op.create_table(
        "roleplay_chats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("character_asset_ids", sa.Text(), nullable=False),
        sa.Column("group", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("messages", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 世界书扩展字段
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("keywords", sa.Text(), nullable=False),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("keysecondary", sa.Text(), nullable=False),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("constant", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("selective", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("selective_logic", sa.String(length=10), nullable=False, server_default="AND_ANY"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("position", sa.String(length=20), nullable=False, server_default="before"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("order_value", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="4"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("role", sa.String(length=10), nullable=False, server_default="system"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("scan_depth", sa.Integer(), nullable=True),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("match_whole_words", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("probability", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "roleplay_lore_entries",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
    )
    # character_name 允许 NULL（全局书）
    op.alter_column(
        "roleplay_lore_entries",
        "character_name",
        existing_type=sa.String(length=100),
        nullable=True,
    )
    # 现有数据：keyword → keywords 数组
    op.execute(
        "UPDATE roleplay_lore_entries SET keywords = "
        "CONCAT('[\\\"', REPLACE(keyword, '\\\"', '\\\\\\\"'), '\\\"]') "
        "WHERE keyword IS NOT NULL AND keyword != ''"
    )
    op.execute("UPDATE roleplay_lore_entries SET keywords = '[]' WHERE keywords = '' OR keywords IS NULL")
    # 正则脚本
    op.create_table(
        "regex_scripts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=False),
        sa.Column("placement", sa.String(length=20), nullable=False, server_default="ai_output"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("character_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 快捷回复
    op.create_table(
        "quick_replies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("character_name", sa.String(length=100), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 用户形象
    op.create_table(
        "roleplay_personas",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("avatar_asset_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("roleplay_personas")
    op.drop_table("quick_replies")
    op.drop_table("regex_scripts")
    op.alter_column(
        "roleplay_lore_entries",
        "character_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.drop_column("roleplay_lore_entries", "enabled")
    op.drop_column("roleplay_lore_entries", "probability")
    op.drop_column("roleplay_lore_entries", "match_whole_words")
    op.drop_column("roleplay_lore_entries", "case_sensitive")
    op.drop_column("roleplay_lore_entries", "scan_depth")
    op.drop_column("roleplay_lore_entries", "role")
    op.drop_column("roleplay_lore_entries", "depth")
    op.drop_column("roleplay_lore_entries", "order_value")
    op.drop_column("roleplay_lore_entries", "position")
    op.drop_column("roleplay_lore_entries", "selective_logic")
    op.drop_column("roleplay_lore_entries", "selective")
    op.drop_column("roleplay_lore_entries", "constant")
    op.drop_column("roleplay_lore_entries", "keysecondary")
    op.drop_column("roleplay_lore_entries", "keywords")
    op.drop_table("roleplay_chats")
    op.drop_table("roleplay_characters")
