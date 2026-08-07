"""用户形象（Persona）：SillyTavern personas 的轻量适配。

用户设定一个身份（名字 + 描述 + 可选头像），聊天时注入 system prompt
（名字替换 {{user}} 宏，描述作为"你的身份"段落）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class RoleplayPersona(Base):
    __tablename__ = "roleplay_personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
