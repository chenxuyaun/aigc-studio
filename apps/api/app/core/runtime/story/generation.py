"""Core Runtime - Story 章节生成编排（P1-3 从 api/v1/story.py 抽离，逐字搬运）。

SSE 流式章节生成（叙事模式）：项目/章节校验 → 角色卡加载 → 提示词构建 →
Provider 流式生成（每 20 chunk 增量落库草稿，断网/刷新不丢内容）→
正则脚本后处理 → 质量报告（确定性预检）→ AI 腔体检 → done 事件。

模块级绑定 resolve_text_provider（conftest._fake_text_resolver 对本模块打补丁）。
产出为 SSE 字符串（含 [DONE] 哨兵），路由层只做 StreamingResponse 包装。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.services import roleplay as rp
from app.services import story_forge
from app.services.provider_resolver import resolve_text_provider
from sqlalchemy.ext.asyncio import AsyncSession


def _sse(ev: dict[str, Any]) -> str:
    """SSE data 行（统一 ensure_ascii=False）。"""
    return "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"


async def stream_chapter_sse(
    db: AsyncSession,
    user_id: str,
    chapter_id: str,
    *,
    project_id: str,
    model: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    instruction: str = "",
) -> AsyncIterator[str]:
    """生成章节正文（SSE 流式，叙事模式）。逐字搬运自原路由 inner _gen。"""
    import re as _re

    project = await story_forge.get_project(db, user_id, project_id)
    chapter = await story_forge.get_chapter(db, user_id, chapter_id)
    if project is None or chapter is None:
        yield _sse({"type": "error", "error": "项目或章节不存在"})
        return
    cards = await rp._load_cards(
        db, user_id, story_forge._load_json(project.character_asset_ids, [])
    )
    if not cards:
        yield _sse({"type": "error", "error": "项目未关联角色卡"})
        return
    system_prompt, user_prompt, wb = await story_forge._build_chapter_prompt(
        db, user_id, project, chapter, cards, instruction
    )
    resolved = await resolve_text_provider(db, model)
    provider = rp.cast_text_provider(resolved.provider)
    chunks: list[str] = []
    try:
        async for chunk in provider.stream_generate(
            user_prompt,
            resolved.model,
            system=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            chunks.append(chunk)
            yield _sse({"type": "chunk", "content": chunk})
            # 断点恢复：每 20 个 chunk 增量落库草稿（status=draft），
            # 刷新/断网后章节保留已生成部分，可继续编辑或重新生成
            if len(chunks) % 20 == 0:
                chapter.content = "".join(chunks)
                chapter.status = "draft"
                await db.commit()
    except Exception as exc:
        # 中断：保留草稿（不丢已生成内容）
        if chunks:
            chapter.content = "".join(chunks)
            chapter.status = "draft"
            await db.commit()
        yield _sse({"type": "error", "error": f"生成失败：{str(exc)[:200]}"})
        yield "data: [DONE]\n\n"
        return
    content = "".join(chunks).strip()
    names = [c.get("name") or "角色" for _, c in cards]
    content = _re.sub(rf"^第\s*{chapter.chapter_no}\s*章.*?\n", "", content, count=1).strip()
    scripts = await rp._load_regex_scripts(db, user_id)
    if scripts:
        content = rp._apply_regex(scripts, content, "ai_output", names)
    chapter.content = content
    chapter.word_count = len(content)
    chapter.model = resolved.model
    chapter.status = "done"
    # 创作内核（P3-5）：确定性预检 → quality_report（零 LLM，流式场景不跑 LLM Critic）
    quality_report = None
    try:
        from app.services.story_gate import deterministic_quality_report

        quality_report = await deterministic_quality_report(db, project, content, chapter)
    except Exception:
        quality_report = None
    await db.commit()
    # AI 腔体检（分级报告：套话/机械句式/连接词/宣传腔/空洞修饰）
    try:
        from app.services.ai_voice_checker import check_ai_voice

        issues = check_ai_voice(content)
    except Exception:
        issues = []
    yield _sse(
        {
            "type": "done",
            "chapter_id": chapter.id,
            "word_count": chapter.word_count,
            "worldbook_hits": len(wb.activated),
            "ai_voice": issues[:12],
            "quality_report": quality_report,
        }
    )
    yield "data: [DONE]\n\n"
