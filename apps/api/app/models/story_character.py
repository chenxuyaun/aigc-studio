"""故事角色实例（Story Character）：角色卡在具体故事中的实例。

一个角色卡可出现在多个项目；实例持有其在本故事中的定位/目标/弧线/当前状态，
并可挂技能（skill_ids → prompt 注入 + MCP 工具白名单）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class StoryCharacter(Base):
    __tablename__ = "story_characters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # 可选：来源角色卡 asset_id（None = 纯文字占位角色）
    character_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # protagonist / supporting
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="supporting", server_default="supporting"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goals: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 角色弧线（成长线）
    arc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 当前状态（每章后由剧务 agent / 手动更新）
    current_state: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON 字符串数组：技能 id（skill_ids）——prompt 注入 + 允许的 MCP 工具
    skill_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：备注
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
