"""创作目标模式（Goal Mode）：用户设目标 → AI 自主拆解执行（复用 agent 工具循环）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.data.models.types import TZDateTime


class CreationGoal(Base):
    __tablename__ = "creation_goals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    goal_text: Mapped[str] = mapped_column(Text, nullable=False)
    # planned / running / succeeded / failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned", server_default="planned"
    )
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
