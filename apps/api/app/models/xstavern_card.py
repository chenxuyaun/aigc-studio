"""xstavern 卡库（外部角色卡市场公开索引，只读浏览用）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class XstavernCard(Base):
    """xstavern.com 角色卡公开索引（slug 唯一；付费墙后的文件本体不在库中）。"""

    __tablename__ = "xstavern_cards"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    author: Mapped[str] = mapped_column(String(50), default="", server_default="")
    category: Mapped[str] = mapped_column(String(60), default="", server_default="", index=True)
    # JSON 字符串数组
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    download_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avg_rating: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preview_url: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
