"""云端聊天会话（saiOS v2 P1：AI 调度大厅会话上云，跨设备同步）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatSession(Base):
    """一条对话会话。id 由前端生成（s-xxx），PUT 全量 upsert 同步。"""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # 前端 s-xxx
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120), default="新会话")
    session_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # 完整消息数组 [{role, content, ts?, media?, toolLog?...}]；条数由 schema 控制
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
