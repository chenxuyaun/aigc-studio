"""Mission 教训（Reflection 沉淀）：失败/自检 → LLM 提炼教训 → 存库 → 后续任务注入。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MissionLesson(Base):
    """一条创作教训：目标 + 教训（失败原因与下次建议）。"""

    __tablename__ = "mission_lessons"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lesson: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
