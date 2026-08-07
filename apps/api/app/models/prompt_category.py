import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import TZDateTime


class PromptCategory(Base):
    __tablename__ = "prompt_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("prompt_categories.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())

    prompts = relationship("Prompt", back_populates="category")
