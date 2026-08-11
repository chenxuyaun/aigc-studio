import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class PromptSource(Base):
    __tablename__ = "prompt_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), default="")
    source_item_url: Mapped[str] = mapped_column(String(500), default="")
    source_author: Mapped[str] = mapped_column(String(200), default="")
    source_license: Mapped[str] = mapped_column(String(100), default="")
    attribution: Mapped[str] = mapped_column(String(500), default="")
    imported_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    prompt_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("prompts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
