"""角色卡市场：xstavern 公开索引浏览（搜索/分类/预览图代理/直链）。"""

from __future__ import annotations

import json
import time as _time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.models.xstavern_card import XstavernCard
from app.security.auth import get_current_user

router = APIRouter(prefix="/cardmarket", tags=["cardmarket"])


def _card_dict(c: XstavernCard) -> dict[str, Any]:
    return {
        "slug": c.slug,
        "name": c.name,
        "author": c.author,
        "category": c.category,
        "tags": json.loads(c.tags or "[]"),
        "nsfw": c.nsfw,
        "download_count": c.download_count,
        "avg_rating": c.avg_rating,
        "summary": c.summary,
        "created_at": str(c.created_at) if c.created_at else "",
    }


@router.get("")
async def list_cards(
    q: str = "",
    category: str = "",
    sort: str = Query("popular", pattern="^(popular|rating|newest|name)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """卡库浏览：关键词/分类筛选，排序（下载/评分/最新/名称）。"""
    stmt = select(XstavernCard)
    if category:
        stmt = stmt.where(XstavernCard.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                XstavernCard.name.like(like),
                XstavernCard.author.like(like),
                XstavernCard.tags.like(like),
            )
        )
    if sort == "popular":
        stmt = stmt.order_by(XstavernCard.download_count.desc())
    elif sort == "rating":
        stmt = stmt.order_by(XstavernCard.avg_rating.desc(), XstavernCard.download_count.desc())
    elif sort == "newest":
        stmt = stmt.order_by(XstavernCard.created_at.desc())
    else:
        stmt = stmt.order_by(XstavernCard.name.asc())

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size)))
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "items": [_card_dict(c) for c in rows],
        "page": page,
        "page_size": page_size,
    }


@router.get("/categories")
async def card_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分类 + 计数（供筛选栏）。"""
    rows = (
        await db.execute(
            select(XstavernCard.category, func.count())
            .group_by(XstavernCard.category)
            .order_by(func.count().desc())
        )
    ).all()
    return {"categories": [{"name": name, "count": int(n)} for name, n in rows]}


# 预览图内存缓存（签名 URL 有时效，缓存 1 小时）
_preview_cache: dict[str, tuple[bytes, str, float]] = {}


async def _fetch_preview(url: str) -> tuple[bytes | None, str | None]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://chat.xstavern.com/"},
            )
        if resp.status_code == 200:
            return resp.content, resp.headers.get("content-type", "image/webp")
    except Exception:
        pass
    return None, None


async def _fresh_preview_url(slug: str) -> str:
    """签名过期时从上游 detail 接口刷新（公开接口，返回带新签名的预览 URL）。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://chat.xstavern.com/api/marketplace.php?action=detail&slug={slug}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if resp.status_code == 200:
            return str((resp.json().get("card") or {}).get("preview_url") or "")
    except Exception:
        pass
    return ""


@router.get("/preview/{slug}")
async def card_preview(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """预览图代理：上游 CDN 防盗链（需 Referer），由后端带 Referer 转发公开图片。

    DB 中的签名 URL 可能过期——失败时从上游 detail 刷新签名再取（内存缓存 1 小时）。
    """
    hit = _preview_cache.get(slug)
    if hit and _time.monotonic() - hit[2] < 3600:
        return Response(
            content=hit[0],
            media_type=hit[1],
            headers={"Cache-Control": "public, max-age=3600"},
        )
    card = (
        await db.execute(select(XstavernCard).where(XstavernCard.slug == slug))
    ).scalar_one_or_none()
    if card is None:
        return Response(status_code=404)
    content, ctype = await _fetch_preview(card.preview_url)
    if not content:
        fresh = await _fresh_preview_url(slug)
        if fresh:
            content, ctype = await _fetch_preview(fresh)
    if not content:
        return Response(status_code=502)
    _preview_cache[slug] = (content, ctype or "image/webp", _time.monotonic())
    return Response(
        content=content,
        media_type=ctype or "image/webp",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/stats")
async def card_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """卡库规模统计。"""
    total = (
        await db.execute(select(func.count()).select_from(XstavernCard))
    ).scalar_one()
    return {"total": int(total)}
