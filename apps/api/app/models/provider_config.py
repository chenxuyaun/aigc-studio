import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    default_model: Mapped[str] = mapped_column(String(100), default="")
    capabilities: Mapped[str] = mapped_column(Text, default="{}")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
