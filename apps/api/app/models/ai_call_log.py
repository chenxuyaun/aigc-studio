import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class AiCallLog(Base):
    """Provider 调用日志：成功 / 回退 / 失败都会留痕，供管理端排查。"""

    __tablename__ = "ai_call_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    task_type: Mapped[str] = mapped_column(String(20), default="", index=True)
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    # succeeded | fallback | failed
    status: Mapped[str] = mapped_column(String(20), default="", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), index=True
    )
