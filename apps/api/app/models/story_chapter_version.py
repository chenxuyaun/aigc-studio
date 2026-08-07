"""章节版本快照（revise/重新生成覆盖前自动保存，可还原）。"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class StoryChapterVersion(Base):
    __tablename__ = "story_chapter_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("story_chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
