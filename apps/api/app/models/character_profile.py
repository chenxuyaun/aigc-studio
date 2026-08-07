"""角色原著档案（character_profiles）：书中角色蒸馏产物。

角色陪伴记忆的"静态层"——书籍文本经 LLM 蒸馏成结构化档案
（身份/性格/说话风格/知识边界/关系网/核心事件）+ 原文分块事实库。
交互记忆（L0-L3）由 MemoryCore gateway 独立管理，不在此表。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime

DISTILL_STATUSES = ("pending", "running", "done", "failed")


class CharacterProfile(Base):
    __tablename__ = "character_profiles"

    # 与角色卡 1:1（asset_id 即 RoleplayCharacter.asset_id）
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # 蒸馏源：知识库文档 id 或空（直接粘贴文本）
    source_doc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    book_title: Mapped[str] = mapped_column(String(200), default="", server_default="")

    # ── 蒸馏产物（LLM 生成）──
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 一句话身份
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 性格
    speech_style: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 说话风格
    knowledge_bounds: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 知识边界
    # JSON 字符串：关系网 [{"name": str, "relation": str, "note": str}]
    relationships: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：核心事件 [{"event": str, "time": str, "impact": str}]
    core_memories: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON 字符串：原文分块事实库 [{"idx": int, "title": str, "text": str}]
    book_chunks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )
