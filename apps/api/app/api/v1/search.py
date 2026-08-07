"""统一本地搜索：一个查询搜知识库/章节/提示词/Agent/素材。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user
from app.services.local_search import SCOPES, SearchResult, search_all

router = APIRouter()


def _to_dict(r: SearchResult) -> dict[str, Any]:
    return {
        "scope": r.scope,
        "id": r.id,
        "title": r.title,
        "snippet": r.snippet,
        "score": r.score,
        "meta": r.meta,
    }


@router.get("")
async def global_search(
    q: str = Query("", min_length=1, max_length=200),
    scope: str = Query("all"),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """全站聚合搜索（纯本地打分，无外部搜索服务）。"""
    scopes = None if scope == "all" else [scope]
    if scopes and scope not in SCOPES:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"未知 scope：{scope}")
    items = await search_all(db, user.id, q, scopes=scopes, limit=limit)
    return {
        "query": q,
        "scope": scope,
        "items": [_to_dict(r) for r in items],
        "total": len(items),
    }
