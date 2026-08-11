"""ASMR 作品收藏（用户维度）。"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class AsmrFavorite(Base):
    __tablename__ = "asmr_favorites"
    __table_args__ = (UniqueConstraint("user_id", "work_id", name="uq_asmr_fav_user_work"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    work_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asmr_works.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
