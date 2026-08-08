from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.generation import MusicGenerationRequest, TaskResponse
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()


class MusicComposeRequest(BaseModel):
    """AI 写歌：主题 → 原创歌词 + 风格描述（供 Suno/网易天音等免费合成）。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="流行", max_length=100)
    mood: str = Field(default="治愈", max_length=100)
    language: str = Field(default="中文", max_length=50)
    verse_count: int = Field(default=2, ge=1, le=4)
    model: str = ""  # 空 = 自动选择文本 Provider（cpa）


_COMPOSE_PROMPT = """你是专业词曲创作人。根据用户要求写一首歌，严格输出 JSON（不要任何多余文字）：

{{
  "title": "歌名",
  "style_zh": "中文风格描述（含乐器/节奏/氛围，给创作者看）",
  "style_en": "英文风格描述（30-60 词，给 AI 音乐生成器如 Suno 用，含 genre/instruments/tempo/mood）",
  "lyrics": "完整歌词，用 \\n 分行，包含 主歌/副歌 结构（用【主歌】【副歌】【桥段】标注），长度为 200-400 字",
  "tips": "一句给使用者的建议（如何用上述内容在 Suno/网易天音生成）"
}}

要求：
- 主题：{theme}
- 风格：{style}
- 情绪：{mood}
- 语言：{language}
- 副歌 {verse_count} 段
- 歌词要真情实感、有画面感、押韵自然
- style_en 必须全是英文，直接可粘贴给 AI 音乐工具"""


def _extract_json(text: str) -> dict[str, Any]:
    """容错解析 LLM 输出的 JSON（剥离 markdown 代码块/前后杂文本）。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"error": "AI 输出解析失败", "raw": text[:500]}


@router.post("/compose", response_model=None)
async def compose_song(
    req: MusicComposeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """AI 写歌（免费）：主题 → 原创歌词 + 风格描述 JSON。走平台文本 Provider（cpa）。"""
    prompt = _COMPOSE_PROMPT.format(
        theme=req.theme, style=req.style, mood=req.mood,
        language=req.language, verse_count=req.verse_count,
    )
    resolved = await resolve_text_provider(db, req.model)
    provider = resolved.provider
    result = await provider.generate(prompt, resolved.model)  # type: ignore[attr-defined]
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    data = _extract_json(text)
    data["provider"] = resolved.model
    return data


@router.post("/generate", response_model=TaskResponse)
async def generate_music(
    req: MusicGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    """音乐生成任务（MusicGen 等 HF 音频模型，prompt 描述风格/情绪/乐器）。"""
    task = await create_media_task(
        db, user_id=user.id, task_type="music", model=req.model, params=req
    )
    return TaskResponse.model_validate(task)
