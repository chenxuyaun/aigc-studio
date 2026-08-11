"""音乐作品：圆桌/写歌定稿的创作资产（歌词+编曲+讨论记录）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MusicWork(Base):
    """一首定稿的歌（创作资产，用户可在「我的创作」随时找回/继续打磨）。"""

    __tablename__ = "music_works"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    theme: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    style: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    lyrics: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    arrangement: Mapped[str] = mapped_column(Text, nullable=False, default="")
    style_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON 字符串数组：讨论记录 [{speaker, content}]
    rounds: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 来源：roundtable（圆桌）/ compose（写歌）/ discuss（讨论室）
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="roundtable")
    # 自动标签：风格/主题/情感，逗号分隔（如 "民谣,劳动者,思乡"）
    tags: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )
