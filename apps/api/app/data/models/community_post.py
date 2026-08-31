"""社区分享墙（批11）：登录用户发布作品，互相浏览与点赞。

不开放匿名注册（安全红线），所有操作都要求已登录；点赞按用户去重。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base


class CommunityPost(Base):
    """一条分享：文字 + 可选图片。"""

    __tablename__ = "community_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    author_name: Mapped[str] = mapped_column(String(60), default="创作者")
    title: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # kind: text | image
    kind: Mapped[str] = mapped_column(String(20), default="text", index=True)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    likes: Mapped[int] = mapped_column(Integer, default=0)
    # 点过赞的 user_id 列表（去重）
    liked_by: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
