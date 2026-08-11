"""正则脚本（RegexScript）：SillyTavern regex 扩展的轻量适配。

placement:
- user_input: 用户消息发送前应用
- ai_output: AI 回复展示前应用（情绪提取之后）
scope:
- global: 所有角色生效
- character: 仅绑定角色生效
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class RegexScript(Base):
    __tablename__ = "regex_scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # 多人创作共享：admin 标记后全员可见可用
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    replacement: Mapped[str] = mapped_column(Text, nullable=False, default="")
    placement: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ai_output")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="global")
    character_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
