"""Core Runtime - Music 作品落库（P1-1 从 api/v1/generations/music.py 抽离）。

- _auto_save_work: 圆桌/写歌定稿自动存入「我的作品」
- _backfill_work_material: 好定稿自动沉淀回知识库（创作范例），带防刷限流
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def _auto_save_work(
    db: AsyncSession,
    *,
    user_id: str,
    theme: str,
    style: str,
    final: dict[str, Any],
    rounds: list[dict[str, str]],
    source: str = "roundtable",
) -> str:
    """定稿自动存入「我的作品」，返回 work_id。"""
    from app.services.music_works import save_work

    work = await save_work(
        db,
        user_id=user_id,
        title=str(final.get("title") or "未命名"),
        theme=theme,
        style=style,
        lyrics=str(final.get("lyrics") or ""),
        chords=str(final.get("chords") or ""),
        arrangement=str(final.get("arrangement") or ""),
        style_en=str(final.get("style_en") or ""),
        rounds=rounds,
        source=source,
    )
    return work.id


# 创作范例回填防刷：每用户每 10 分钟最多 1 篇（进程内）
_backfill_lock: dict[str, float] = {}
_BACKFILL_MIN_INTERVAL = 600.0


async def _backfill_work_material(
    *,
    user_id: str,
    work_title: str,
    theme: str,
    lyrics: str,
    chords: str,
    arrangement: str,
) -> None:
    """好定稿自动沉淀回知识库（创作范例）：检索命中后成为后续创作的营养。

    条件：自检无严重警告（由调用方把关）+ 标题去重（同用户已有同名范例则跳过）
    + 每用户每 10 分钟最多 1 篇。任何失败静默（不影响创作主流程）。
    """
    if not work_title or not lyrics or len(lyrics) < 200:
        return
    import time as _time

    now = _time.monotonic()
    last = _backfill_lock.get(user_id, 0.0)
    if now - last < _BACKFILL_MIN_INTERVAL:
        return
    _backfill_lock[user_id] = now
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.text_document import TextDocument
        from app.services.knowledge_materials import summarize_for_creation
        from sqlalchemy import select

        title = f"创作范例·{work_title}"
        content = (
            f"创作主题：{theme}\n\n【定稿歌词】\n{lyrics}\n\n【和弦谱】\n{chords or '（无）'}"
            f"\n\n【编曲思路】\n{arrangement or '（无）'}"
        )
        async with AsyncSessionLocal() as session:
            dup = await session.execute(
                select(TextDocument.id)
                .where(TextDocument.user_id == user_id, TextDocument.title == title)
                .limit(1)
            )
            if dup.scalar_one_or_none():
                return
            interpretation = await summarize_for_creation(session, title, content)
            if interpretation:
                content = content + "\n\n" + interpretation
            # AI 自动写入的素材默认待确认（pending）：确认前不参与检索，防幻觉污染
            session.add(
                TextDocument(title=title, content=content, user_id=user_id, status="pending")
            )
            await session.commit()
    except Exception:
        pass
