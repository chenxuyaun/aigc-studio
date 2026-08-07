import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class PromptFavorite(Base):
    __tablename__ = "prompt_favorites"
    __table_args__ = (UniqueConstraint("user_id", "prompt_id", name="uq_user_prompt_favorite"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
