"""ASMR 聚合库：多来源 ASMR 作品元数据（asmr.one 为主源，其余站点尽力采集）。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime

ASMR_SOURCES = ("asmr_one", "asmrmoon", "asmrgay")


class AsmrWork(Base):
    """ASMR 作品元数据条目（幂等 upsert：source + source_work_id 唯一）。"""

    __tablename__ = "asmr_works"
    __table_args__ = (
        UniqueConstraint("source", "source_work_id", name="uq_asmr_source_work"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_work_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # RJ 编号
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    circle_name: Mapped[str] = mapped_column(String(200), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)  # 日元
    release_date: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    rate_average: Mapped[float] = mapped_column(Float, default=0.0)
    dl_count: Mapped[int] = mapped_column(Integer, default=0)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    age_category: Mapped[str] = mapped_column(String(20), default="adult")
    vas: Mapped[str] = mapped_column(Text, default="[]")  # JSON 声优数组
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON [{name, zh}]
    langs: Mapped[str] = mapped_column(Text, default="[]")  # JSON 语言数组（JPN/CHI_HANS/ENG…）
    has_chinese: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    has_subtitle: Mapped[bool] = mapped_column(Boolean, default=False)
    cover_url: Mapped[str] = mapped_column(String(1000), default="")
    main_cover_url: Mapped[str] = mapped_column(String(1000), default="")
    thumbnail_url: Mapped[str] = mapped_column(String(1000), default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
