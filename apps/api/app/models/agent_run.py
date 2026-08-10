"""Agent 运行时（Agent Runtime）：Agent 库实例 → 可被 Orchestrator 调度的执行单元。

Agent Instance = Identity（name/system_prompt）+ Goal（本次任务）+ Memory（教训/素材注入）
              + Tools（agent.tools）+ State（agent_runs 留痕）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentRun(Base):
    """一次 Agent 执行留痕（State：idle→running→done/failed）。"""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="done")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
