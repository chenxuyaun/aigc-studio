import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class GenerationTask(Base):
    __tablename__ = "generation_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str] = mapped_column(Text, default="")
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("provider_configs.id"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
