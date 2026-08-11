"""自动连载调度（Serial Schedule）：定时为项目生成下一章。

celery beat 每分钟 tick（serial_tick）扫描 next_run_at <= now 的 active 调度，
为项目创建 chapter 生成任务（后台任务化），随后 next_run_at += interval。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class SerialSchedule(Base):
    __tablename__ = "serial_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # 两次生成间隔（分钟）
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # 每次批量生成的章节数
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_run_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    # 已生成章节数
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # active / paused
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    # 剧本模式（群聊产出）或叙事模式
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="narrative", server_default="narrative"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 连续失败计数（>=3 自动暂停，防死循环刷失败任务）
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
