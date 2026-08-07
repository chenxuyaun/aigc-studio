"""AgentList 外部 AI Agent 项目目录接入端点。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agentlist import AgentArticle, AgentComparison, AgentProject
from app.models.user import User
from app.security.auth import get_current_user
from app.services import agentlist_ingest

router = APIRouter(tags=["agentlist"])

# 同步互斥：防并发触发重复下载+全表更新
_sync_lock = asyncio.Lock()
_sync_running = False


def _json_list(v: str) -> list[str]:
    try:
        data = json.loads(v or "[]")
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _project_dict(p: AgentProject) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "url": p.url,
        "github_url": p.github_url,
        "homepage_url": p.homepage_url,
        "description": p.description,
        "categories": _json_list(p.categories),
        "tags": _json_list(p.tags),
        "stars": p.stars,
        "language": p.language,
        "license": p.license,
    }


@router.get("/agentlist/projects")
async def list_projects(
    search: str = "",
    category: str = "",
    language: str = "",
    min_stars: int = 0,
    sort: str = "stars",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """项目目录：搜索（名称/描述/标签）+ 分类/语言过滤 + 星数排序。"""
    stmt = select(AgentProject)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                AgentProject.name.like(like),
                AgentProject.description.like(like),
                AgentProject.tags.like(like),
            )
        )
    if category:
        stmt = stmt.where(AgentProject.categories.like(f"%{category}%"))
    if language:
        stmt = stmt.where(AgentProject.language == language)
    if min_stars > 0:
        stmt = stmt.where(AgentProject.stars >= min_stars)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    order = (
        AgentProject.stars.desc()
        if sort == "stars"
        else AgentProject.name.asc()
        if sort == "name"
        else AgentProject.updated_at.desc()
    )
    rows = (await db.execute(stmt.order_by(order).limit(limit).offset(offset))).scalars().all()
    return {"items": [_project_dict(p) for p in rows], "total": total}


@router.get("/agentlist/projects/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    p = (
        await db.execute(select(AgentProject).where(AgentProject.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="项目不存在")
    return {"project": _project_dict(p)}


def _article_dict(a: AgentArticle, with_content: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "description": a.description,
        "categories": _json_list(a.categories),
        "related_projects": _json_list(a.related_projects),
    }
    if with_content:
        d["content"] = a.content
    return d


@router.get("/agentlist/articles")
async def list_articles(
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AgentArticle)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(AgentArticle.title.like(like), AgentArticle.description.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        (await db.execute(stmt.order_by(AgentArticle.title.asc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return {"items": [_article_dict(a) for a in rows], "total": total}


@router.get("/agentlist/articles/{article_id}")
async def get_article(
    article_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    a = (
        await db.execute(select(AgentArticle).where(AgentArticle.id == article_id))
    ).scalar_one_or_none()
    if a is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="文章不存在")
    return {"article": _article_dict(a, with_content=True)}


def _comparison_dict(c: AgentComparison, with_content: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": c.id,
        "title": c.title,
        "url": c.url,
        "description": c.description,
        "categories": _json_list(c.categories),
        "projects": _json_list(c.projects),
    }
    if with_content:
        d["content"] = c.content
    return d


@router.get("/agentlist/comparisons")
async def list_comparisons(
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AgentComparison)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(AgentComparison.title.like(like), AgentComparison.description.like(like))
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        (await db.execute(stmt.order_by(AgentComparison.title.asc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return {"items": [_comparison_dict(c) for c in rows], "total": total}


@router.get("/agentlist/comparisons/{comparison_id}")
async def get_comparison(
    comparison_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    c = (
        await db.execute(select(AgentComparison).where(AgentComparison.id == comparison_id))
    ).scalar_one_or_none()
    if c is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="对比表不存在")
    return {"comparison": _comparison_dict(c, with_content=True)}


@router.get("/agentlist/stats")
async def agentlist_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """目录统计：总量 + 分类分布 + 语言分布。"""
    counts = await agentlist_ingest.count_agentlist(db)
    cats: dict[str, int] = {}
    langs: dict[str, int] = {}
    for cat in (await db.execute(select(AgentProject.categories))).scalars().all():
        for c in _json_list(cat):
            cats[c] = cats.get(c, 0) + 1
    for lang in (await db.execute(select(AgentProject.language))).scalars().all():
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:15]
    top_langs = sorted(langs.items(), key=lambda x: -x[1])[:10]
    return {"counts": counts, "top_categories": top_cats, "top_languages": top_langs}


@router.post("/agentlist/sync")
async def sync_agentlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """拉取最新 llms-full.txt 并幂等入库（admin）。"""
    if user.role != "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="仅管理员可同步")
    global _sync_running
    if _sync_running:
        return {"ok": False, "error": "同步进行中，请稍候"}
    async with _sync_lock:
        _sync_running = True
        try:
            counts = await agentlist_ingest.sync_agentlist(db)
        finally:
            _sync_running = False
    return {"ok": True, **counts}
