"""创作项目（Story Project）：以角色扮演方式创作的载体（story bible）。

一本书/一个剧本 = 一个项目：关联角色卡、项目级世界书（lore.project_id）、
章节（story_chapters）、角色实例（story_characters）、连载调度（serial_schedules）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class StoryProject(Base):
    __tablename__ = "story_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    genre: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # drafting / ongoing / completed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="drafting", server_default="drafting"
    )
    # JSON 字符串数组：角色卡 asset_id 列表（story_characters 的素材来源）
    character_asset_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：扩展设置（默认模型、语言、视角等）
    settings: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
