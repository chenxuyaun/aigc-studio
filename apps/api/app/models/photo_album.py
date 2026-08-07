import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class PhotoAlbum(Base):
    """写真摄影相册：承载一批风格/主题一致的参考图。"""

    __tablename__ = "photo_albums"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    cover_photo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    style_tags: Mapped[str] = mapped_column(String(500), default="")  # 逗号分隔
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
