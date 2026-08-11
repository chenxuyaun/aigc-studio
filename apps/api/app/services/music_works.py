"""音乐作品服务：定稿保存/列表/删除（创作资产沉淀）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.music_work import MusicWork


async def save_work(
    db: AsyncSession,
    *,
    user_id: str,
    title: str,
    theme: str = "",
    style: str = "",
    lyrics: str = "",
    chords: str = "",
    arrangement: str = "",
    style_en: str = "",
    rounds: list[dict[str, str]] | None = None,
    source: str = "roundtable",
    tags: str = "",
) -> MusicWork:
    """保存一首定稿作品（rounds 为讨论记录 JSON）。tags 为空时自动提取。"""
    work = MusicWork(
        user_id=user_id,
        title=(title or "未命名")[:100],
        theme=theme[:500],
        style=style[:100],
        lyrics=lyrics,
        chords=chords,
        arrangement=arrangement,
        style_en=style_en,
        rounds=json.dumps(rounds or [], ensure_ascii=False),
        source=source,
        tags=tags[:200] or await _auto_tags(db, title, theme, style, lyrics),
    )
    db.add(work)
    await db.commit()
    await db.refresh(work)
    return work


_TAG_PROMPT = """为一首歌提取 2-4 个标签（风格/主题/情感，每个 2-5 字，逗号分隔）。
规则：从歌词内容提取真实主题（如劳动者/思乡/离别/成长），不臆造；风格标签取自给定的风格。
输出 JSON（不要任何多余文字）：{{"tags": "标签1,标签2"}}

歌名：{title}
风格：{style}
主题：{theme}

歌词：
{lyrics}"""


async def _auto_tags(db: AsyncSession, title: str, theme: str, style: str, lyrics: str) -> str:
    """LLM 自动打标签（风格/主题/情感）；失败降级为风格标签（不阻塞保存）。"""
    try:
        from app.services.provider_resolver import resolve_text_provider

        resolved = await resolve_text_provider(db, "")
        prompt = _TAG_PROMPT.format(
            title=(title or "未命名")[:60],
            style=(style or "未知")[:30],
            theme=(theme or "")[:120],
            lyrics=(lyrics or "")[:1200],
        )
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.3
        )
        if isinstance(result, dict):
            text = str(result.get("text") or result.get("content") or "")
        elif hasattr(result, "content"):
            text = str(result.content)
        else:
            text = str(result)
        import re

        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            import json as _json

            tags = str(_json.loads(cleaned[start : end + 1]).get("tags") or "").strip()
            if tags:
                return ",".join(t.strip() for t in tags.split(",") if t.strip())[:200]
    except Exception:
        pass
    return (style or "").strip()[:60]


async def list_works(
    db: AsyncSession, user_id: str, limit: int = 50, q: str = "", tag: str = ""
) -> list[dict[str, Any]]:
    stmt = (
        select(MusicWork)
        .where(MusicWork.user_id == user_id)
        .order_by(MusicWork.created_at.desc())
        .limit(limit)
    )
    if q.strip():
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            MusicWork.title.like(kw) | MusicWork.theme.like(kw) | MusicWork.style.like(kw)
        )
    if tag.strip():
        stmt = stmt.where(MusicWork.tags.like(f"%{tag.strip()}%"))
    rows = (await db.execute(stmt)).scalars().all()
    return [_work_dict(w) for w in rows]


async def delete_work(db: AsyncSession, user_id: str, work_id: str) -> bool:
    result = await db.execute(
        delete(MusicWork).where(MusicWork.id == work_id, MusicWork.user_id == user_id)
    )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


def _work_dict(w: MusicWork) -> dict[str, Any]:
    try:
        rounds = json.loads(w.rounds or "[]")
    except Exception:
        rounds = []
    return {
        "id": w.id,
        "title": w.title,
        "theme": w.theme,
        "style": w.style,
        "lyrics": w.lyrics,
        "chords": w.chords,
        "arrangement": w.arrangement,
        "style_en": w.style_en,
        "rounds": rounds if isinstance(rounds, list) else [],
        "source": w.source,
        "tags": w.tags or "",
        "created_at": str(w.created_at) if w.created_at else "",
        "updated_at": str(w.updated_at) if w.updated_at else "",
    }
