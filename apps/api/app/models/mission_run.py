"""Mission 任务会话（持久化）：目标/计划/结果/汇总完整入库，可回看复用。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MissionRun(Base):
    """一次任务总控会话（长期协作记忆：平台记得你下达过的目标与结果）。"""

    __tablename__ = "mission_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON：计划 [{step, kind, title}]
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON：结果 [{step, kind, title, summary, ok, task_id}]
    results: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
