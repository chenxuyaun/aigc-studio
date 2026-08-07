"""统一本地搜索：多 scope 全文打分（纯 Python，无向量/搜索服务依赖）。

复用 knowledge_retrieval 的 tokenize（中文单字+英文词切分，无需分词器），
对每个 scope 的标题/正文打分排序，产出统一结果结构。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.asmr_work import AsmrWork
from app.models.asset import Asset
from app.models.prompt import Prompt
from app.models.story_chapter import StoryChapter
from app.models.story_project import StoryProject
from app.models.text_document import TextDocument
from app.services.knowledge_retrieval import tokenize

SCOPES = ("knowledge", "story", "prompts", "agents", "assets", "asmr")
MAX_PER_SCOPE = 20  # 单 scope 结果上限
MAX_TOTAL = 50  # 总结果上限（防滥用）
_SNIPPET_SIZE = 120


@dataclass
class SearchResult:
    scope: str
    id: str
    title: str
    snippet: str
    score: int
    meta: dict[str, Any] = field(default_factory=dict)


def _score(query_tokens: Counter[str], text: str, title: str = "") -> int:
    """标题 token 权重 2x，正文 1x。"""
    return score_text(query_tokens, title) * 2 + score_text(query_tokens, text)


def _continuity_bonus(query: str, text: str) -> int:
    """查询连续子串（2-6 字）出现在文本中的加分——中文单字切分的补救。

    单字 token 碰撞（「设」命中「设计」）会制造噪音，连续子串命中才是真相关。
    """
    q = query.lower()
    t = text.lower()
    bonus = 0
    for n in (6, 5, 4, 3, 2):
        for i in range(max(0, len(q) - n + 1)):
            if q[i : i + n] in t:
                bonus += n
                break
        if bonus:
            break
    return bonus


def score_text(query_tokens: Counter[str], text: str) -> int:
    if not text:
        return 0
    tokens = Counter(tokenize(text))
    return sum(min(query_tokens[t], tokens[t]) for t in query_tokens)


def _escape_like(term: str) -> str:
    """LIKE 通配符转义（DB 预筛用，避免 token 里的 %/_ 被当通配符）。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text: str, query_tokens: Counter[str], size: int = _SNIPPET_SIZE) -> str:
    """定位第一个命中 token 所在窗口作为摘要，避免截断到无关开头。"""
    if not text:
        return ""
    tokens = tokenize(text)
    positions: list[int] = []
    for i, t in enumerate(tokens):
        if query_tokens[t] > 0:
            positions.append(i)
    if not positions:
        return text[:size]
    # 取命中位置映射回字符偏移（tokenize 是字符级切分，用累计长度近似）
    char_idx = _token_char_offset(text, tokens, positions[0])
    start = max(0, char_idx - size // 4)
    return text[start : start + size]


def _token_char_offset(text: str, tokens: list[str], token_idx: int) -> int:
    """token 序号 → 文本字符偏移（单字/单词长度近似）。"""
    return sum(len(t) for t in tokens[:token_idx])


def _distinct_hits(query_tokens: Counter[str], text: str) -> int:
    """查询中多少个不同 token 出现在文本中（含标题拼接文本）。"""
    if not text:
        return 0
    tokens = set(tokenize(text))
    return sum(1 for t in query_tokens if t in tokens)


def _mk(
    scope: str, id_: str, title: str, text: str,
    query: str, q: Counter[str], meta: dict[str, Any] | None = None,
) -> SearchResult | None:
    token_score = _score(q, text, title)
    if token_score < 1:
        return None
    # 多字查询：至少 2 个不同 token 命中，或存在连续子串命中（防单字碰撞噪音）
    if len(query) >= 2:
        haystack = f"{title}\n{text}"
        if _distinct_hits(q, haystack) < 2 and _continuity_bonus(query, haystack) < 2:
            return None
    return SearchResult(
        scope=scope,
        id=id_,
        title=title,
        snippet=_snippet(text, q),
        score=token_score,
        meta=meta or {},
    )


async def search_all(
    db: AsyncSession,
    user_id: str,
    query: str,
    scopes: list[str] | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """全站聚合搜索：本人数据 + public 内容。返回按分数降序。"""
    q = (query or "").strip()
    if not q:
        return []
    q_tokens = Counter(tokenize(q))
    if not q_tokens:
        return []
    scope_set = set(scopes or SCOPES)
    limit = max(1, min(limit, MAX_TOTAL))
    results: list[SearchResult] = []

    # ── knowledge：本人文档 ──
    if "knowledge" in scope_set:
        doc_rows = (
            await db.execute(
                select(TextDocument)
                .where(TextDocument.user_id == user_id)
                .order_by(TextDocument.updated_at.desc())
                .limit(500)
            )
        ).scalars().all()
        for doc in doc_rows:
            res = _mk(
                "knowledge", doc.id, doc.title,
                f"{doc.title}\n{doc.content or ''}", q, q_tokens,
            )
            if res:
                results.append(res)

    # ── story：本人章节（含项目梗概）──
    if "story" in scope_set:
        chapter_rows = (
            await db.execute(
                select(StoryChapter)
                .where(StoryChapter.user_id == user_id)
                .order_by(StoryChapter.updated_at.desc())
                .limit(500)
            )
        ).scalars().all()
        projects = {
            p.id: p
            for p in (
                await db.execute(
                    select(StoryProject).where(
                        StoryProject.id.in_({c.project_id for c in chapter_rows})
                    )
                )
            ).scalars().all()
        }
        for ch in chapter_rows:
            proj = projects.get(ch.project_id)
            proj_text = proj.synopsis or "" if proj else ""
            text = f"{ch.title}\n{ch.outline or ''}\n{ch.content or ''}\n{proj_text}"
            res = _mk(
                "story",
                ch.id,
                f"{ch.title}（{proj.title if proj else '项目'}）",
                text,
                q,
                q_tokens,
                {
                    "project_id": ch.project_id,
                    "chapter_no": ch.chapter_no,
                    "project_title": proj.title if proj else "",
                    "status": ch.status,
                },
            )
            if res:
                results.append(res)

    # ── prompts：public 或本人 ──
    if "prompts" in scope_set:
        prompt_rows = (
            await db.execute(
                select(Prompt).where(
                    or_(Prompt.is_public.is_(True), Prompt.author_id == user_id)
                )
                .order_by(Prompt.updated_at.desc())
                .limit(500)
            )
        ).scalars().all()
        for pr in prompt_rows:
            res = _mk(
                "prompts", pr.id, pr.title,
                f"{pr.title}\n{pr.content or ''}", q, q_tokens,
            )
            if res:
                results.append(res)

    # ── agents：public 或本人 ──
    if "agents" in scope_set:
        agent_rows = (
            await db.execute(
                select(Agent).where(
                    or_(Agent.is_public.is_(True), Agent.author_id == user_id)
                )
                .order_by(Agent.updated_at.desc())
                .limit(500)
            )
        ).scalars().all()
        for ag in agent_rows:
            text = f"{ag.name}\n{ag.description or ''}\n{ag.system_prompt or ''}"
            res = _mk("agents", ag.id, ag.name, text, q, q_tokens)
            if res:
                results.append(res)

    # ── assets：本人素材 ──
    if "assets" in scope_set:
        asset_rows = (
            await db.execute(
                select(Asset)
                .where(Asset.user_id == user_id)
                .order_by(Asset.created_at.desc())
                .limit(500)
            )
        ).scalars().all()
        for asst in asset_rows:
            res = _mk(
                "assets", asst.id, asst.filename or "",
                asst.filename or "", q, q_tokens,
            )
            if res:
                results.append(res)

    # ── asmr：作品库（全站公开聚合数据）──
    if "asmr" in scope_set:
        # DB 层预筛（标题/社团/声优/标签任一 token LIKE 命中）替代 2000 行全拉，
        # 召回与 _mk 打分一致（LIKE 匹配 ⊇ token 命中），再 limit 300 进内存打分
        asmr_stmt = select(AsmrWork).order_by(AsmrWork.release_date.desc())
        like_clauses: list[Any] = []
        for tok in q_tokens:
            like = f"%{_escape_like(tok)}%"
            like_clauses.append(AsmrWork.title.like(like))
            like_clauses.append(AsmrWork.circle_name.like(like))
            like_clauses.append(AsmrWork.vas.like(like))
            like_clauses.append(AsmrWork.tags.like(like))
        if like_clauses:
            asmr_stmt = asmr_stmt.where(or_(*like_clauses))
        asmr_rows = (
            await db.execute(asmr_stmt.limit(300))
        ).scalars().all()
        for aw in asmr_rows:
            text = f"{aw.title}\n{aw.circle_name}\n{aw.vas}\n{aw.tags}"
            res = _mk(
                "asmr", aw.id, aw.title,
                text, q, q_tokens,
                {
                    "source_work_id": aw.source_work_id,
                    "rate_average": aw.rate_average,
                    "nsfw": aw.nsfw,
                    "has_chinese": aw.has_chinese,
                },
            )
            if res:
                results.append(res)

    results.sort(key=lambda r: -r.score)
    return results[:limit]


async def search_project(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    """项目内搜索：本项目章节 + 梗概 + 本人知识库文档（供编辑器「查找前文」）。"""
    q = (query or "").strip()
    if not q:
        return []
    q_tokens = Counter(tokenize(q))
    if not q_tokens:
        return []
    limit = max(1, min(limit, MAX_TOTAL))
    results: list[SearchResult] = []

    proj = (
        await db.execute(
            select(StoryProject).where(
                StoryProject.id == project_id, StoryProject.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if proj is None:
        return []
    if proj.synopsis:
        r = _mk(
            "story", proj.id, proj.title, proj.synopsis, q, q_tokens,
            {"project_id": proj.id, "chapter_no": 0, "project_title": proj.title},
        )
        if r:
            results.append(r)

    chapters = (
        await db.execute(
            select(StoryChapter)
            .where(StoryChapter.project_id == project_id, StoryChapter.user_id == user_id)
            .order_by(StoryChapter.chapter_no.asc())
        )
    ).scalars().all()
    for c in chapters:
        text = f"{c.title}\n{c.outline or ''}\n{c.content or ''}"
        r = _mk(
            "story",
            c.id,
            f"第{c.chapter_no}章 {c.title}",
            text,
            q,
            q_tokens,
            {
                "project_id": project_id,
                "chapter_no": c.chapter_no,
                "project_title": proj.title,
                "status": c.status,
            },
        )
        if r:
            results.append(r)

    docs = (
        await db.execute(
            select(TextDocument)
            .where(TextDocument.user_id == user_id)
            .order_by(TextDocument.updated_at.desc())
            .limit(200)
        )
    ).scalars().all()
    for d in docs:
        r = _mk("knowledge", d.id, d.title, f"{d.title}\n{d.content or ''}", q, q_tokens)
        if r:
            results.append(r)

    results.sort(key=lambda r: -r.score)
    return results[:limit]
