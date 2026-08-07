import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import TZDateTime


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_categories.id", ondelete="SET NULL"), nullable=True
    )
    workflow_type: Mapped[str] = mapped_column(String(20), default="sequential", nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    cover_url: Mapped[str] = mapped_column(String(1000), default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    source_author: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )

    author = relationship("User")
    category = relationship("WorkflowCategory", back_populates="workflows")
