"""AI 生命体成长系统（批8+9）：成长日记 + 对用户的长期记忆条目。

- GrowthDiary：每积累若干轮对话，后台 LLM 反思生成一篇（干了什么/学到什么/亮点）。
- MemoryEntry：从对话中提炼的跨会话记忆（偏好/事实/事件/情感），
  新对话自动注入 system prompt——AI 开始"记得你"。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base


class GrowthDiary(Base):
    """一篇成长日记：来源会话 + 摘要 + 教训/亮点列表。"""

    __tablename__ = "ai_growth_diary"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    summary: Mapped[str] = mapped_column(String(500), default="")
    lessons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    highlights: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # 反思时该会话的消息数——节流依据（新增不足 N 条不重复反思）
    msg_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())


class MemoryEntry(Base):
    """一条对用户的长期记忆。kind: preference|fact|event|emotion。"""

    __tablename__ = "ai_memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="fact", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    source_session_id: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )
