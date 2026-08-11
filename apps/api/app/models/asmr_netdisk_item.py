"""ASMR 网盘资源条目（asmrgay Alist 公开 API 聚合的目录元数据）。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class AsmrNetdiskItem(Base):
    """网盘资源条目（目录/作品文件夹）。"""

    __tablename__ = "asmr_netdisk_items"
    __table_args__ = (UniqueConstraint("source", "path", name="uq_asmr_disk_source_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    is_dir: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    modified: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
