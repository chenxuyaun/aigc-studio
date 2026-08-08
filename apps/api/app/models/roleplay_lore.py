"""角色扮演世界书条目（SillyTavern World Info / Lorebook 适配版）。

匹配机制（对齐 ST 1.18）：
- keywords 主关键词（可含正则 /.../ 语法）
- keysecondary 次关键词（selective 判定）
- constant 常驻条目无条件激活
- position: before=主提示前 / after=主提示后 / atDepth=聊天中部第 depth 条消息后
- order 排序（大者优先注入）；probability 激活概率
- 兼容旧字段 keyword（迁移时写入 keywords 数组首项）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class RoleplayLoreEntry(Base):
    __tablename__ = "roleplay_lore_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # 多人创作共享：admin 标记后全员可见可用
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # None = 全局书（任何角色命中都注入）；否则绑定角色名
    character_name: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    # 创作项目作用域（story_projects.id）；None = 常规角色扮演/全局
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 兼容旧字段（保留）；新代码优先 keywords
    keyword: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    # JSON 字符串数组：主关键词
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串数组：次关键词（selective 用）
    keysecondary: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    constant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    selective: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # AND_ANY / AND_ALL / NOT_ANY / NOT_ALL
    selective_logic: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="AND_ANY"
    )
    # before / after / atDepth
    position: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="before"
    )
    order_value: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    # atDepth 时的深度（距末尾第 N 条后）与注入角色
    depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4, server_default="4"
    )
    role: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="system"
    )
    scan_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_sensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    match_whole_words: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
