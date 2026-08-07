"""每日巡检报告（系统健康度快照，供工作台展示）。"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class InspectionReport(Base):
    __tablename__ = "inspection_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
