"""角色卡（RoleplayCharacter）：SillyTavern V2 全字段，与 assets 表一一对应。

PNG 二进制仍在 assets 表（统一存储后端）；本表存解析出的结构化字段，
供编辑、导入导出、prompt 组装使用。JSON 字段用 Text 存字符串（MySQL/SQLite 兼容）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class RoleplayCharacter(Base):
    __tablename__ = "roleplay_characters"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_mes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mes_example: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON 字符串数组：备用开场白
    alternate_greetings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_history_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creator_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON 字符串数组：标签
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：内嵌世界书 {"name": str, "entries": {uid: entry}}
    character_book: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 群聊话痨度 0~1（SillyTavern extensions.talkativeness）
    talkativeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # JSON 字符串：深度提示 {"depth": 4, "prompt": "", "role": "system"}
    depth_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON 字符串：扩展字段兜底（creator/character_version/fav 等）
    settings: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
