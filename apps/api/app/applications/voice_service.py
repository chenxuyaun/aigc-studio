"""Personal Voice Engine 服务（去 AI 味 → 像具体的人）。

核心思路（非禁词表降重）——Voice DNA + Personal Corpus：
- Voice DNA：句式/用词/口吻/情绪/幽默/观点强度 + preferred[]/avoid[]/openings[]/endings[]
  （描述「这个人怎么写」，而不是「AI 味长什么样」）
- Personal Corpus：用户真实表达片段（聊天、文档、记忆、手动加料）作参照

对外函数：
- get_profile / get_or_create_profile      档案读取（读路径不落库）
- update_profile                            手动编辑（source → manual）
- auto_extract_profile                      LLM 从语料提炼 DNA（失败静默降级为规则统计）
- add_corpus / list_corpus                  个人语料条目管理
- build_voice_injection                     生成 system 级「文风档案」注入文案（≤900 字符）

设计约束：
- 提取/注入失败**静默降级**，绝不影响主链路（同 growth_service 模式）
- 写路径显式 commit（get_db 不自动提交）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.provider_resolver import resolve_text_provider
from app.models.chat_session import ChatSession
from app.models.growth import MemoryEntry
from app.models.text_document import TextDocument
from app.models.voice import VoiceCorpus, VoiceProfile

logger = logging.getLogger("aigc.voice")

_INJECT_CHARS = 900  # system prompt 文风注入字符预算
_CORPUS_CHARS = 400  # 单条语料入库截断
_CORPUS_LIMIT = 200  # 每用户语料条数上限（超出淘汰最旧）
_CORPUS_KINDS = ("article", "chat", "note", "lyric", "story")
_EXTRACT_CORPUS_CHARS = 4000  # 送入 LLM 提炼的语料总预算
_SAMPLE_INJECT_CHARS = 200  # 注入时单条范文截断
_MAX_SAMPLES_INJECT = 2  # 注入时最多带几条范文

# Voice DNA 字段默认值（JSON 可序列化，前端表单可编辑）
_DNA_DEFAULTS: dict[str, Any] = {
    "sentence_length": "mixed",  # short|medium|long|mixed
    "vocabulary": "simple",  # simple|medium|rich
    "formality": "medium",  # casual|medium|formal
    "emotion": "restrained",  # restrained|warm|expressive
    "humor": "dry",  # none|dry|witty
    "opinion_strength": "high",  # low|medium|high
    "preferred": [],  # 表达习惯（喜欢怎样写）
    "avoid": [],  # 忌讳（绝不这样写）
    "openings": [],  # 常用开头
    "endings": [],  # 常用收尾
}

_EXTRACT_PROMPT = """你是文风分析师。下面提供一段某位用户的「个人语料」
（TA 自己的聊天、笔记或文档片段）。请提炼 TA 的 Voice DNA——写作人格档案，
**只输出一个 JSON 对象，不要多余文字**：

{{
  "sentence_length": "short|medium|long|mixed",
  "vocabulary": "simple|medium|rich",
  "formality": "casual|medium|formal",
  "emotion": "restrained|warm|expressive",
  "humor": "none|dry|witty",
  "opinion_strength": "low|medium|high",
  "preferred": ["TA 的表达习惯，2-6 条，每条 ≤8 字，具体可执行"],
  "avoid": ["TA 不会用的腔调/写法，2-6 条，每条 ≤8 字"],
  "openings": ["TA 常用的开头方式，0-3 条"],
  "endings": ["TA 常用的收尾方式，0-3 条"]
}}

判定标准：
- 只依据语料里**有证据**的特征下结论；语料不足以判断的字段给中性值。
- preferred/avoid 要具体（如「短句」「口头禅式开头」），不要空泛（如「文笔好」）。
- 语料过少时 preferred/avoid 给空数组。

个人语料：
"""


def _default_dna() -> dict[str, Any]:
    return json.loads(json.dumps(_DNA_DEFAULTS))


async def get_profile(db: AsyncSession, user_id: str) -> VoiceProfile | None:
    """读取用户文风档案（不存在返回 None，不落库）。"""
    return (
        (
            await db.execute(
                select(VoiceProfile).where(VoiceProfile.user_id == user_id).limit(1)
            )
        )
        .scalars()
        .first()
    )


async def get_or_create_profile(db: AsyncSession, user_id: str) -> VoiceProfile:
    """读取或初始化档案（仅 flush，不 commit——读路径不产生副作用）。"""
    p = await get_profile(db, user_id)
    if p:
        return p
    p = VoiceProfile(user_id=user_id, name="我的文风", voice_dna=_default_dna())
    db.add(p)
    await db.flush()
    return p


async def update_profile(
    db: AsyncSession,
    user_id: str,
    *,
    name: str | None = None,
    dna: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
) -> VoiceProfile:
    """手动编辑档案（upsert：无档案则建档；写路径 commit）。"""
    p = await get_or_create_profile(db, user_id)
    if name is not None:
        p.name = str(name).strip()[:50] or "我的文风"
    if dna is not None and isinstance(dna, dict):
        merged = _default_dna()
        merged.update({k: v for k, v in dna.items() if v is not None})
        p.voice_dna = merged
    if samples is not None:
        p.samples = _clean_samples(samples)
    p.source = "manual"
    await db.commit()
    await db.refresh(p)
    return p


async def auto_extract_profile(
    db: AsyncSession, user_id: str
) -> VoiceProfile | None:
    """从语料自动提炼 Voice DNA（LLM 辅助，失败静默降级为规则统计）。

    - 无语料 → 返回 None（不建档）
    - 已有 manual 档案 → 不覆盖手动配置，原样返回
    - 已有 auto 档案 → 用新提炼结果刷新（保留既有非空键）
    """
    corpus = await _gather_corpus(db, user_id)
    if not corpus:
        return None
    p = await get_or_create_profile(db, user_id)
    if p.source == "manual":
        return p  # 用户显式配置过：自动提炼不覆盖
    parsed = await _extract_dna_llm(db, corpus)
    if not parsed:
        parsed = _extract_dna_rules(corpus)
    if not parsed:
        return p
    existing = p.voice_dna or {}
    # auto 刷新：新提炼结果优先，保留既有非空键（如用户曾半手动补过的字段）
    merged = {**{k: v for k, v in existing.items() if v}, **parsed}
    p.voice_dna = {**_default_dna(), **merged}
    p.source = "auto"
    await db.commit()
    await db.refresh(p)
    return p


async def build_voice_injection(
    db: AsyncSession, user_id: str, user_query: str = ""
) -> str:
    """组装 system 级「文风档案」注入文本；无档案时返回空串（静默）。"""
    p = await get_profile(db, user_id)
    if not p:
        return ""
    dna = p.voice_dna or {}
    lines: list[str] = []
    labels = {
        "sentence_length": "句式",
        "vocabulary": "用词",
        "formality": "口吻",
        "emotion": "情绪",
        "humor": "幽默",
        "opinion_strength": "观点",
    }
    for key, zh in labels.items():
        val = dna.get(key)
        if val:
            lines.append(f"- {zh}：{val}")
    preferred = [str(x).strip() for x in (dna.get("preferred") or []) if str(x).strip()]
    avoid = [str(x).strip() for x in (dna.get("avoid") or []) if str(x).strip()]
    if preferred:
        lines.append("- 喜欢：" + "；".join(preferred))
    if avoid:
        lines.append("- 忌讳：" + "；".join(avoid))

    sample_lines: list[str] = []
    for s in (p.samples or [])[: _MAX_SAMPLES_INJECT]:
        text = str((s.get("text") if isinstance(s, dict) else s) or "").strip()
        if text:
            sample_lines.append(text[: _SAMPLE_INJECT_CHARS])
    if not lines and not sample_lines:
        return ""

    head = "以下是这位用户的「文风档案」。请以 TA 的口吻写作——自然地用，不要复述这份档案："
    parts = [head, *lines]
    if sample_lines:
        parts.append("\n参考范文（模仿其节奏，不要照抄内容）：")
        parts.append("\n".join(f"【范文】{t}" for t in sample_lines))
    text = "\n".join(parts)
    if len(text) > _INJECT_CHARS:
        text = text[: _INJECT_CHARS].rsplit("\n", 1)[0]
    return text


async def add_corpus(
    db: AsyncSession,
    user_id: str,
    kind: str,
    text: str,
    source_ref: str = "",
) -> VoiceCorpus | None:
    """新增一条个人语料（写路径 commit）。kind 非法或文本过短返回 None。"""
    kind = kind if kind in _CORPUS_KINDS else "chat"
    text = str(text or "").strip()
    if len(text) < 8:
        return None
    item = VoiceCorpus(
        user_id=user_id,
        kind=kind,
        text_snippet=text[: _CORPUS_CHARS],
        source_ref=str(source_ref or "")[:100],
    )
    # 先 prune 再 add：同一事务里 DELETE 会连带删掉刚 add 的新行
    # （第 201+ 条时），commit 后 refresh 找不到行会抛 InvalidRequestError
    await _prune_corpus(db, user_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def list_corpus(
    db: AsyncSession, user_id: str, kind: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """列出个人语料（新→旧）。"""
    stmt = select(VoiceCorpus).where(VoiceCorpus.user_id == user_id)
    if kind:
        stmt = stmt.where(VoiceCorpus.kind == kind)
    rows = (
        (
            await db.execute(
                stmt.order_by(VoiceCorpus.created_at.desc()).limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "text": r.text_snippet,
            "source_ref": r.source_ref,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


async def _gather_corpus(db: AsyncSession, user_id: str) -> list[str]:
    """收集用户真实表达片段：记忆偏好 + 聊天用户消息 + 已确认文档 + 手动语料。"""
    chunks: list[str] = []
    total = 0

    mem_rows = (
        (
            await db.execute(
                select(MemoryEntry)
                .where(
                    MemoryEntry.user_id == user_id,
                    MemoryEntry.kind.in_(("preference", "fact")),
                )
                .order_by(MemoryEntry.updated_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    for r in mem_rows:
        line = f"[{r.kind}] {r.content}"
        if total + len(line) > _EXTRACT_CORPUS_CHARS:
            break
        chunks.append(line)
        total += len(line)

    sess_rows = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatSession.updated_at.desc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    for s in sess_rows:
        for m in (s.messages or [])[-20:]:
            if (m.get("role") or "") != "user":
                continue
            text = str(m.get("content") or "").strip()
            if len(text) < 10:
                continue
            line = text[:200]
            if total + len(line) > _EXTRACT_CORPUS_CHARS:
                return chunks
            chunks.append(line)
            total += len(line)

    doc_rows = (
        (
            await db.execute(
                select(TextDocument)
                .where(
                    TextDocument.user_id == user_id,
                    TextDocument.status == "confirmed",
                )
                .order_by(TextDocument.updated_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    for d in doc_rows:
        line = str(d.content or "").strip()[:300]
        if len(line) < 10:
            continue
        if total + len(line) > _EXTRACT_CORPUS_CHARS:
            break
        chunks.append(line)
        total += len(line)

    corp_rows = (
        (
            await db.execute(
                select(VoiceCorpus)
                .where(VoiceCorpus.user_id == user_id)
                .order_by(VoiceCorpus.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    for c in corp_rows:
        line = str(c.text_snippet or "").strip()[:200]
        if total + len(line) > _EXTRACT_CORPUS_CHARS:
            break
        chunks.append(line)
        total += len(line)

    return chunks


async def _extract_dna_llm(db: AsyncSession, corpus: list[str]) -> dict[str, Any] | None:
    """LLM 提炼 Voice DNA；任何失败返回 None（调用方降级规则统计）。"""
    try:
        resolved = await resolve_text_provider(db, "")
        prompt = _EXTRACT_PROMPT + "\n".join(corpus)[-6000:]
        result = await resolved.provider.generate(prompt, resolved.model)
        obj = _parse_json_block(result.content or "")
        if not obj:
            return None
        picked: dict[str, Any] = {}
        for key in _DNA_DEFAULTS:
            if key in obj:
                picked[key] = obj[key]
        return picked if picked else None
    except Exception:
        logger.warning("voice_extract_llm_failed", exc_info=True)
        return None


def _extract_dna_rules(corpus: list[str]) -> dict[str, Any] | None:
    """LLM 不可用时的规则统计兜底：句式长短 + 情绪基调。"""
    texts = [t for t in corpus if t.strip()]
    if not texts:
        return None
    sentences = []
    for t in texts:
        sentences += [s for s in re.split(r"[。！？!?…\n]", t) if len(s) >= 2]
    avg = sum(len(s) for s in sentences) / max(len(sentences), 1) if sentences else 20
    if avg < 14:
        sentence_length = "short"
    elif avg > 26:
        sentence_length = "long"
    else:
        sentence_length = "mixed"
    exclaim = sum(t.count("！") + t.count("!") for t in texts)
    emotion = "expressive" if exclaim / max(len(texts), 1) > 0.5 else "restrained"
    return {"sentence_length": sentence_length, "emotion": emotion}


def _parse_json_block(text: str) -> dict[str, Any] | None:
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


def _clean_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in samples[:10]:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "title": str(s.get("title") or "").strip()[:50],
                "text": text[: _CORPUS_CHARS],
            }
        )
    return out


async def _prune_corpus(db: AsyncSession, user_id: str) -> None:
    rows = (
        (
            await db.execute(
                select(VoiceCorpus.id)
                .where(VoiceCorpus.user_id == user_id)
                .order_by(VoiceCorpus.created_at.desc())
                .offset(_CORPUS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if rows:
        await db.execute(
            VoiceCorpus.__table__.delete().where(VoiceCorpus.id.in_(list(rows)))
        )
