"""AI 生命体反思服务（批8+9）。

对话收尾后调用：把最近对话交给 LLM 提炼——
1. 一篇成长日记（干了什么 / 学到什么 / 亮点）
2. 若干条对用户的长期记忆（偏好/事实/事件/情感），去重后入库

设计约束：
- 反思失败**静默降级**（绝不影响主对话链路）
- 节流：同一会话新增消息不足 _MIN_NEW_MESSAGES 条不重复反思
- 注入预算：记忆文本 ≤ 900 字符，超出按 updated_at 新→旧截断
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.provider_resolver import resolve_text_provider
from app.models.chat_session import ChatSession
from app.models.growth import GrowthDiary, MemoryEntry

logger = logging.getLogger("aigc.growth")

_MIN_NEW_MESSAGES = 4  # 距上次反思新增消息数阈值
_MAX_TAIL_MESSAGES = 14  # 送入反思的最近消息条数
_MEMORY_LIMIT = 60  # 每用户记忆条目上限（超出淘汰最旧）
_INJECT_CHARS = 900  # system prompt 记忆注入字符预算

_KINDS = ("preference", "fact", "event", "emotion")

_REFLECT_PROMPT = """你是 AI 助手的自我反思模块。下面是一段你与用户的对话记录。
请提炼两部分内容，**只输出一个 JSON 对象，不要多余文字**：

{{
  "summary": "本次对话做了什么（≤80字，第三人称描述 AI 的行为）",
  "lessons": ["AI 从中学到的经验/改进点，0-3 条，每条 ≤40 字"],
  "highlights": ["值得记录的成果/亮点，0-3 条，每条 ≤40 字"],
  "memories": [
    {{"kind": "preference|fact|event|emotion", "content": "对用户的长期记忆，≤60 字，具体可复用"}}
  ]
}}

memories 提炼标准：
- preference：用户明确表达的喜好/习惯（如"喜欢赛博朋克风格"）
- fact：用户背景事实（如"在做毕业设计"）
- event：重要事件（如"下周要参加面试"）
- emotion：情绪基调（如"最近因项目延期焦虑"）
- 只记稳定、可复用的信息；闲聊寒暄不要记；没有就给空数组。
- kind 必须是以上四种之一。

对话记录：
"""


async def reflect_session(db: AsyncSession, user_id: str, session_id: str) -> dict | None:
    """对一个会话做一次反思。返回日记 dict；节流跳过或失败返回 None。

    注意：后台任务请通过 reflect_session_bg（自开 session）调用，
    本函数接受外部传入的 db，便于测试与复用。
    """
    row = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if not row:
        return None
    messages = row.messages or []
    user_msgs = [m for m in messages if (m.get("role") or "") in ("user", "assistant")]
    if len(user_msgs) < _MIN_NEW_MESSAGES:
        return None

    last = (
        await db.execute(
            select(GrowthDiary)
            .where(GrowthDiary.session_id == session_id, GrowthDiary.user_id == user_id)
            .order_by(GrowthDiary.created_at.desc(), GrowthDiary.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last and (len(user_msgs) - int(last.msg_count or 0)) < _MIN_NEW_MESSAGES:
        return None  # 节流：新增不多，不重复反思

    tail = user_msgs[-_MAX_TAIL_MESSAGES:]
    transcript = "\n".join(
        f"{'用户' if (m.get('role') == 'user') else 'AI'}: {str(m.get('content') or '')[:500]}"
        for m in tail
        if str(m.get("content") or "").strip()
    )
    if not transcript.strip():
        return None

    parsed = await _reflect_llm(db, transcript)
    if not parsed:
        return None

    diary = GrowthDiary(
        user_id=user_id,
        session_id=session_id,
        summary=str(parsed.get("summary") or "")[:500],
        lessons=_as_str_list(parsed.get("lessons")),
        highlights=_as_str_list(parsed.get("highlights")),
        msg_count=len(user_msgs),
    )
    db.add(diary)

    added = 0
    for mem in (parsed.get("memories") or [])[:8]:
        if not isinstance(mem, dict):
            continue
        kind = str(mem.get("kind") or "").strip()
        content = str(mem.get("content") or "").strip()[:300]
        if kind not in _KINDS or not content:
            continue
        dup = (
            await db.execute(
                select(MemoryEntry.id).where(
                    MemoryEntry.user_id == user_id, MemoryEntry.content == content
                )
            )
        ).first()
        if dup:
            continue
        db.add(
            MemoryEntry(
                user_id=user_id,
                kind=kind,
                content=content,
                source_session_id=session_id,
            )
        )
        added += 1
    await _evict_overflow(db, user_id)
    await db.commit()

    logger.info(
        "growth_reflected",
        extra={"session_id": session_id, "user_id": user_id, "mem_added": added},
    )
    return {
        "id": diary.id,
        "summary": diary.summary,
        "lessons": diary.lessons,
        "highlights": diary.highlights,
        "memories_added": added,
    }


async def reflect_session_bg(user_id: str, session_id: str) -> None:
    """后台反思入口：自开短生命周期 session（请求结束后原 db 已关闭）。"""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            await reflect_session(s, user_id, session_id)
    except Exception:
        logger.warning("growth_reflect_failed", exc_info=True)


async def build_memory_injection(
    db: AsyncSession, user_id: str, user_query: str = "", k: int = 12
) -> str:
    """组装 system 级记忆注入文本；无记忆返回空串。

    方向 B（top-k 相关性检索）：user_query 非空时按
    0.65×n-gram 余弦相关性 + 0.35×新近度 选 top-k 条（app.applications.memory_rank）；
    user_query 为空时保持旧行为（按新→旧取前 k 条）。
    """
    rows = (
        (
            await db.execute(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(120)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return ""
    try:
        from app.applications.memory_rank import rank_memories

        idx = rank_memories(user_query, [r.content for r in rows], k=k)
        rows = [rows[i] for i in idx]
    except Exception:
        rows = rows[:k]
    label = {"preference": "偏好", "fact": "背景", "event": "事件", "emotion": "情绪"}
    parts: list[str] = []
    total = 0
    for r in rows:
        line = f"- [{label.get(r.kind, r.kind)}] {r.content}"
        if total + len(line) > _INJECT_CHARS:
            break
        parts.append(line)
        total += len(line)
    if not parts:
        return ""
    return (
        "以下是你在过往交流中记住的关于这位用户的长期信息（自然运用即可，"
        "不要向用户复述这份列表）：\n" + "\n".join(parts)
    )


async def _evict_overflow(db: AsyncSession, user_id: str) -> None:
    rows = (
        (
            await db.execute(
                select(MemoryEntry.id)
                .where(MemoryEntry.user_id == user_id)
                .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id.desc())
                .offset(_MEMORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if rows:
        await db.execute(
            MemoryEntry.__table__.delete().where(MemoryEntry.id.in_(list(rows)))
        )


def _as_str_list(v: object) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip()[:80] for x in v if str(x).strip()][:3]


async def _reflect_llm(db: AsyncSession, transcript: str) -> dict | None:
    try:
        resolved = await resolve_text_provider(db, "")
        prompt = _REFLECT_PROMPT + transcript[-6000:]
        result = await resolved.provider.generate(prompt, resolved.model)
        return _parse_json_block(result.content or "")
    except Exception:
        logger.warning("growth_reflect_llm_failed", exc_info=True)
        return None


def _parse_json_block(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
