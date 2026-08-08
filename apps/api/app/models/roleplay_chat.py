"""角色扮演聊天会话（roleplay_chats）：服务端持久化的对话历史。

messages 为 JSON 字符串数组：
[{"role": "user"|"assistant", "content": str, "mood": str?, "created_at": str?}]
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class RoleplayChat(Base):
    __tablename__ = "roleplay_chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # JSON 字符串数组：参与的角色卡 asset_id 列表
    character_asset_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # 多人同场演出：房间会话对全员可见可加入（真人+AI 角色同场）
    is_room: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # JSON 字符串数组：消息历史
    messages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model: Mapped[str] = mapped_column(String(100), default="", server_default="")
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON 字符串：作者注/所选 persona 等 {"note": {...}, "persona_id": str}
    settings: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
