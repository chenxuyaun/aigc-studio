"""故事章节（Story Chapter）：创作引擎的产出单元。

outline = 该章大纲；content = 正文（叙事体或剧本模式产出）；
status: outline（只有大纲）/ draft（草稿）/ done（完成）。
task_id 关联后台生成任务（任务化/连载路径）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class StoryChapter(Base):
    __tablename__ = "story_chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    outline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # outline / draft / done
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="outline", server_default="outline"
    )
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # JSON 字符串：生成参数与备注
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
