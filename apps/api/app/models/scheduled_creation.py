"""定时创作（Scheduled Creations）：周期性地把 prompt 作为生成任务入队。"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class ScheduledCreation(Base):
    __tablename__ = "scheduled_creations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # 生成任务类型：text / image / audio（对应现有 Celery 队列）
    task_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text"
    )
    # 调度类型：daily（每天某时刻）/ interval（每隔 N 小时）
    schedule_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # 每日执行时刻（HH:MM），schedule_type=daily 时必填
    daily_time: Mapped[time | None] = mapped_column(Time(), nullable=True)
    # 周期小时数，schedule_type=interval 时必填
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    next_run_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_result_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
