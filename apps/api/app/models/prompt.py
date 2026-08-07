import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import TZDateTime


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("prompt_categories.id", ondelete="SET NULL"), nullable=True
    )
    prompt_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    # 外部来源（如 prompt.qqsrc.com 画廊）：封面图直链图床 CDN。
    # 图床为 Cloudflare R2 公开桶（见 scripts/backfill_qqsrc_covers.py 的 IMG_BASE，
    # 勿用 qqsrc.com 域名——该域名只服务 SPA，图片路径会 404 fallback 成 HTML）。
    # 保留来源链接与作者署名。
    cover_url: Mapped[str] = mapped_column(String(1000), default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    source_author: Mapped[str] = mapped_column(String(200), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )

    author = relationship("User", back_populates="prompts")
    category = relationship("PromptCategory", back_populates="prompts")
    tags = relationship("PromptTag", secondary="prompt_tag_relations", back_populates="prompts")
