"""原著蒸馏：书籍文本 → 角色档案 + 原文分块事实库。

流程（celery 任务内执行）：
1. 取源文本（知识库文档 TextDocument 或直接粘贴）
2. 长文先按块做 LLM 摘要（控制 token 预算），短文直接截断
3. LLM 一次调用生成结构化档案 JSON（身份/性格/说话风格/知识边界/关系网/核心事件）
4. 原文分块（复用 knowledge_retrieval.chunk_text）存 book_chunks 供召回检索
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_profile import CharacterProfile
from app.models.roleplay_character import RoleplayCharacter
from app.models.text_document import TextDocument
from app.services.knowledge_retrieval import chunk_text
from app.services.provider_resolver import resolve_text_provider

logger = logging.getLogger("aigc.distill")

# 直接生成档案的文本上限（超过则先摘要）
_DIRECT_LIMIT = 40000
# 摘要分块大小与每批块数
_SUMMARY_CHUNK = 10000
_SUMMARY_BATCH = 8
# 档案生成输入预算（摘要拼接后）
_DISTILL_INPUT_LIMIT = 32000

_PROFILE_SYSTEM = """你是资深角色塑造专家。从给定的小说/故事文本中蒸馏出指定角色的完整档案，用于后续 AI 扮演该角色陪伴读者。

输出严格 JSON（不要 markdown 代码块）：
{
  "identity": "一句话身份（≤100字），如：XX国落魄贵族家的长女，表面温柔实则腹黑",
  "personality": "性格特质（≤400字），含优缺点、深层动机、口头禅倾向",
  "speech_style": "说话风格（≤300字），含语气、用词习惯、称谓方式、情绪表达特点",
  "knowledge_bounds": "知识边界（≤200字）：该角色知道什么（书中事实/时代背景）、不知道什么",
  "relationships": [{"name": "角色名", "relation": "与ta的关系", "note": "关系细节（≤40字）"}],  # noqa: E501
  "core_memories": [{"event": "事件（≤60字）", "time": "发生时机", "impact": "对角色影响（≤40字）"}]
}
要求：只依据给定文本蒸馏，不脑补文本外的设定；relationships 最多 12 条；core_memories 最多 15 条。

【目标角色匹配（强制）】必须精确蒸馏【目标角色】字段中指定的角色——以该角色的全名/称呼为准，优先匹配文本中明确出现该名字的角色。若文本中找不到与目标角色名对应的角色，则输出：
{"identity": "未找到角色", "personality": "", "speech_style": "", "knowledge_bounds": "", "relationships": [], "core_memories": []}
禁止擅自选择其他角色代替目标角色。"""  # noqa: E501


def _extract_json(text: str) -> dict[str, Any] | None:
    """容错解析 LLM 输出（直接 JSON / ```json 块 / 截断补全）。"""
    if not text:
        return None
    cleaned = text.strip()
    # 提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if m:
        cleaned = m.group(1).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    # 截断场景：尝试逐行拼接直到括号闭合
    for cut in range(len(cleaned), 0, -256):
        try:
            data = json.loads(cleaned[:cut])
            return data if isinstance(data, dict) else None
        except Exception:
            continue
    return None


async def _generate(
    db: AsyncSession,
    system: str,
    user: str,
    max_tokens: int = 4000,
) -> str:
    """调默认文本 provider 生成（失败抛异常由任务层记录）。"""
    from app.services.roleplay import cast_text_provider

    resolved = await resolve_text_provider(db, "")
    provider = cast_text_provider(resolved.provider)
    result = await provider.generate(
        user,
        resolved.model,
        system=system,
        max_tokens=max_tokens,
        temperature=0.4,
    )
    return result.content


async def _summarize_long_text(db: AsyncSession, text: str) -> str:
    """长文分块摘要：一次调用批量输出每块 ≤300 字摘要。"""
    blocks = [text[i : i + _SUMMARY_CHUNK] for i in range(0, len(text), _SUMMARY_CHUNK)]
    summaries: list[str] = []
    for start in range(0, len(blocks), _SUMMARY_BATCH):
        batch = blocks[start : start + _SUMMARY_BATCH]
        user = (
            "以下是小说文本片段（每段以 【片段N】 开头）。请为每段输出 ≤300 字的中文摘要，"
            "保留与角色相关的情节、对话、人物关系细节。输出 JSON 数组，"
            '格式：[{"idx": 0, "summary": "..."}, ...]\n\n'
            + "\n\n".join(f"【片段{i}】\n{seg}" for i, seg in enumerate(batch))
        )
        raw = await _generate(
            db,
            "你是小说内容摘要助手，只输出 JSON 数组。",
            user,
            max_tokens=3000,
        )
        try:
            data = json.loads(raw)
            for item in data if isinstance(data, list) else []:
                if isinstance(item, dict) and item.get("summary"):
                    summaries.append(str(item["summary"]))
        except Exception:
            # 摘要失败降级：直接截断原文片段
            summaries.append(batch[0][:1500])
    return "\n\n".join(summaries)


async def distill_profile(
    db: AsyncSession,
    user_id: str,
    asset_id: str,
    doc_id: str | None = None,
    text: str | None = None,
    book_title: str | None = None,
) -> CharacterProfile:
    """执行蒸馏（任务内调用）：生成档案 + 分块事实库，写回 profile 记录。"""
    character = (
        await db.execute(
            select(RoleplayCharacter).where(
                RoleplayCharacter.asset_id == asset_id,
                RoleplayCharacter.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if character is None:
        raise ValueError("角色卡不存在")

    # 源文本
    source = text or ""
    book_title = book_title or character.name
    if doc_id:
        doc = (
            await db.execute(
                select(TextDocument).where(
                    TextDocument.id == doc_id, TextDocument.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            raise ValueError("知识库文档不存在")
        source = doc.content or ""
        book_title = doc.title or character.name
    source = source.strip()
    if not source:
        raise ValueError("没有可蒸馏的文本（文档为空或未提供文本）")
    if len(source) > 2_000_000:
        raise ValueError("文本过长（>200 万字符）")

    profile = (
        await db.execute(
            select(CharacterProfile).where(
                CharacterProfile.asset_id == asset_id,
                CharacterProfile.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = CharacterProfile(
            asset_id=asset_id,
            user_id=user_id,
            source_doc_id=doc_id,
            book_title=book_title,
        )
        db.add(profile)
    else:
        profile.source_doc_id = doc_id
        profile.book_title = book_title
    profile.status = "running"
    profile.error = ""
    await db.commit()

    try:
        # 长文先摘要，短文直接截断
        if len(source) > _DIRECT_LIMIT:
            distilled_text = await _summarize_long_text(db, source)
            distilled_text = distilled_text[:_DISTILL_INPUT_LIMIT]
        else:
            distilled_text = source[:_DISTILL_INPUT_LIMIT]

        user_prompt = (
            f"【书名】{book_title}\n"
            f"【目标角色】{character.name}\n"
            f"【文本】\n{distilled_text}\n\n"
            "请输出该角色的完整档案 JSON。"
        )
        raw = await _generate(db, _PROFILE_SYSTEM, user_prompt, max_tokens=4000)
        data = _extract_json(raw)
        if data is None:
            raise ValueError("蒸馏结果解析失败")

        if str(data.get("identity") or "")[:20] == "未找到角色":
            raise ValueError(f"文本中未找到目标角色「{character.name}」，请检查书名/文本")
        profile.identity = str(data.get("identity") or "")[:500]
        profile.personality = str(data.get("personality") or "")[:2000]
        profile.speech_style = str(data.get("speech_style") or "")[:1500]
        profile.knowledge_bounds = str(data.get("knowledge_bounds") or "")[:1000]
        profile.relationships = json.dumps(data.get("relationships") or [], ensure_ascii=False)[
            :20000
        ]
        profile.core_memories = json.dumps(data.get("core_memories") or [], ensure_ascii=False)[
            :20000
        ]

        # 原文分块事实库（召回检索用）
        chunks = chunk_text(source)
        profile.book_chunks = json.dumps(
            [
                {"idx": i, "title": f"{book_title}·第{i + 1}段", "text": c}
                for i, c in enumerate(chunks)
            ],
            ensure_ascii=False,
        )[:1_000_000]

        profile.status = "done"
        await db.commit()
    except Exception as exc:
        profile.status = "failed"
        profile.error = str(exc)[:500]
        await db.commit()
        raise
    return profile
