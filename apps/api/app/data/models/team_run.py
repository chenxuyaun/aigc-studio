"""Agent 团队协作（批10）：一次目标 → 规划分工 → 成员接力 → 汇总报告。

诚实的协作模型：成员按规划顺序**串行接力**（后者能看到前者的产出），
不是并行多智能体编排——每一步都是一次真实的 LLM 调用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base


class TeamRun(Base):
    """一次团队协作运行。steps 随执行进度增量写入（前端轮询可见）。"""

    __tablename__ = "team_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    # planning | running | done | failed
    status: Mapped[str] = mapped_column(String(20), default="planning", index=True)
    members: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{name,role,task}]
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{name,role,output}]
    final_report: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )
