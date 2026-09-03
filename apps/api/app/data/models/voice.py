"""Personal Voice Engine：用户文风档案（Voice DNA）与个人语料库。

- VoiceProfile：每用户一份可显式编辑/自动提取的「文风档案」——
  句式、用词、口吻、偏好与忌讳（preferred/avoid），供生成时注入 system。
- VoiceCorpus：从用户聊天/创作/笔记沉淀的真实表达片段，
  作为 auto-extract 与 Style Reference 的个人语料来源。

设计取向（非禁词表降重）：档案描述「这个人怎么写」，而不是「AI 味长什么样」。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base


class VoiceProfile(Base):
    """一份用户文风档案。source: manual|auto|mixed"""

    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(50), default="我的文风")
    # Voice DNA（JSON dict）：{sentence_length, vocabulary, formality, emotion,
    # humor, opinion_strength, preferred[], avoid[], openings[], endings[]}
    voice_dna: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 范文/风格样本：[{title, text, source?}]
    samples: Mapped[list[Any]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(10), default="auto", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )


class VoiceCorpus(Base):
    """一条个人语料。kind: article|chat|note|lyric|story"""

    __tablename__ = "voice_corpus"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="chat", index=True)
    text_snippet: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
