import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class TextDocument(Base):
    __tablename__ = "text_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generation_tasks.id"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # confirmed=已确认（参与检索）/ pending=AI 自动写入待确认（确认前不参与检索，防幻觉污染）
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="confirmed", server_default="confirmed"
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )

    @property
    def char_count(self) -> int:
        return len(self.content)
