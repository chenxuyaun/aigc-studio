"""快捷回复（QuickReply）：SillyTavern quick-reply 扩展的轻量适配。

输入框上方一行按钮，点击后把 message（支持宏 {{char}}/{{user}} 等）填入输入框或直接发送。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class QuickReply(Base):
    __tablename__ = "quick_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="global")
    character_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # auto=True：用户发送消息后自动触发（后端随响应返回建议）
    auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
