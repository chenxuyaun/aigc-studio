import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import TZDateTime


class PromptTag(Base):
    __tablename__ = "prompt_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())

    prompts = relationship("Prompt", secondary="prompt_tag_relations", back_populates="tags")
