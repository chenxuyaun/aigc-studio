"""ASMR 聚合库端点：作品列表/详情/统计/手动同步。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_clear_prefix, cache_json_get, cache_json_set
from app.core.database import get_db
from app.models.asmr_work import AsmrWork
from app.models.user import User
from app.security.auth import get_current_user
from app.services import asmr_ingest
from app.storage import get_storage

router = APIRouter(tags=["asmr"])

_sync_lock = asyncio.Lock()
_sync_running = False

# 列表查询缓存 TTL（秒）；同步入库后按前缀失效
_WORKS_CACHE_TTL = 600


def _json_list(v: str) -> list[Any]:
    try:
        data = json.loads(v or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _like_pattern(term: str) -> str:
    """LIKE 通配符转义（JSON Text 列里做标签预筛用）。"""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _work_dict(w: AsmrWork, with_details: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": w.id,
        "source": w.source,
        "source_work_id": w.source_work_id,
        "title": w.title,
        "circle_name": w.circle_name,
        "price": w.price,
        "release_date": w.release_date.isoformat() if w.release_date else None,
        "duration_seconds": w.duration_seconds,
        "rate_average": w.rate_average,
        "dl_count": w.dl_count,
        "nsfw": w.nsfw,
        "age_category": w.age_category,
        "has_chinese": w.has_chinese,
        "langs": _json_list(w.langs),
        "has_subtitle": w.has_subtitle,
        "cover_url": w.cover_url,
        "thumbnail_url": w.thumbnail_url,
        "source_url": w.source_url,
    }
    if with_details:
        d["vas"] = _json_list(w.vas)
        d["tags"] = _json_list(w.tags)
    return d


@router.get("/works")
async def list_works(
    q: str = "",
    tag: str = "",
    nsfw: str = Query("all", pattern="^(all|adult|general)$"),
    lang: str = Query("all", pattern="^(all|zh|jp|en)$"),
    source: str = "",
    sort: str = Query("date", pattern="^(date|rate|dl_count|price)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """作品列表：关键词（标题/社团/声优）+ 标签 + 分级 + 语言 + 来源 + 排序 + 分页。

    LIKE 全表扫描热路径：结果走 Redis 缓存（10 分钟 TTL，同步后清前缀失效）。
    """
    # 缓存 key：过滤/排序/分页参数的稳定哈希（用户维度不影响数据，可共享）
    cache_key = (
        "asmr:works:v1:"
        + hashlib.sha256(
            json.dumps(
                [q.strip().lower(), tag.strip().lower(), nsfw, lang, source, sort, page, page_size],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    cached = await cache_json_get(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached

    stmt = select(AsmrWork)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                AsmrWork.title.like(like),
                AsmrWork.circle_name.like(like),
                AsmrWork.vas.like(like),
            )
        )
    if tag:
        stmt = stmt.where(AsmrWork.tags.like(f"%{tag.strip()}%"))
    if nsfw == "adult":
        stmt = stmt.where(AsmrWork.nsfw.is_(True))
    elif nsfw == "general":
        stmt = stmt.where(AsmrWork.nsfw.is_(False))
    if lang == "zh":
        stmt = stmt.where(AsmrWork.has_chinese.is_(True))
    elif lang == "jp":
        stmt = stmt.where(AsmrWork.langs.like("%JPN%"))
    elif lang == "en":
        stmt = stmt.where(AsmrWork.langs.like("%ENG%"))
    if source:
        stmt = stmt.where(AsmrWork.source == source)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order: Any = AsmrWork.release_date.desc()
    if sort == "rate":
        order = AsmrWork.rate_average.desc()
    elif sort == "dl_count":
        order = AsmrWork.dl_count.desc()
    elif sort == "price":
        order = AsmrWork.price.desc()
    rows = (
        (
            await db.execute(
                stmt.order_by(order, AsmrWork.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    payload: dict[str, Any] = {
        "items": [_work_dict(w) for w in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }
    await cache_json_set(cache_key, payload, ttl=_WORKS_CACHE_TTL)
    return payload


@router.get("/cover/{work_id}")
async def get_cover(
    work_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """封面图本地缓存代理：首次下载源站封面存本地，之后直接读本地（源站封了图也不丢）。

    匿名可访问（<img> 标签请求不携带 Authorization）；封面为公开图片数据，
    本地库 work_id 为 UUID 不可枚举，配合全局限流防滥用。
    """

    w = (await db.execute(select(AsmrWork).where(AsmrWork.id == work_id))).scalar_one_or_none()
    if w is None or not w.cover_url:
        raise HTTPException(status_code=404, detail="封面不存在")

    # 大图优先（详情弹窗不模糊）；缓存 key 区分尺寸（旧 key 存的是小图）
    src_url = w.main_cover_url or w.cover_url
    key = f"asmr_covers/m/{w.id}.jpg" if w.main_cover_url else f"asmr_covers/{w.id}.jpg"
    try:
        data = await get_storage("local").get(key)
    except FileNotFoundError:
        data = b""
    except Exception:
        data = b""

    if not data:
        # 下载源站封面（限时、限大小）
        import httpx

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    src_url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://asmr.one/"},
                )
                resp.raise_for_status()
                data = resp.content[: 4 * 1024 * 1024]
            if data:
                await get_storage("local").put(key, data, "image/jpeg")
        except Exception:
            data = b""

    if not data:
        raise HTTPException(status_code=404, detail="封面获取失败")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/works/{work_id}/similar")
async def similar_works(
    work_id: str,
    limit: int = Query(6, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """相似作品：标签重叠 + 同声优加分（同分级优先）。"""
    w = (await db.execute(select(AsmrWork).where(AsmrWork.id == work_id))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    my_tags = {str(t.get("name") or "") for t in _json_list(w.tags)}
    my_vas = {str(v) for v in _json_list(w.vas)}

    # 标签预筛（JSON Text 列 LIKE）+ 确定性排序，避免取任意 500 条无关子集
    stmt = select(AsmrWork).where(
        AsmrWork.id != work_id,
        AsmrWork.nsfw == w.nsfw,
    )
    tag_likes = [_like_pattern(t) for t in list(my_tags)[:10]]
    if tag_likes:
        stmt = stmt.where(or_(*[AsmrWork.tags.like(pat, escape="\\") for pat in tag_likes]))
    stmt = stmt.order_by(AsmrWork.release_date.desc(), AsmrWork.id.desc()).limit(500)
    rows = (await db.execute(stmt)).scalars().all()

    scored: list[tuple[int, AsmrWork]] = []
    for other in rows:
        o_tags = {str(t.get("name") or "") for t in _json_list(other.tags)}
        o_vas = {str(v) for v in _json_list(other.vas)}
        score = len(my_tags & o_tags) * 2 + len(my_vas & o_vas)
        if score > 0:
            scored.append((score, other))
    scored.sort(key=lambda x: (-x[0], -(x[1].rate_average or 0)))
    # 标签命中不足时补最近发布的作品（避免相似推荐空窗）
    if len(scored) < limit:
        more = (
            (
                await db.execute(
                    select(AsmrWork)
                    .where(
                        AsmrWork.id != work_id,
                        AsmrWork.nsfw == w.nsfw,
                    )
                    .order_by(AsmrWork.release_date.desc(), AsmrWork.id.desc())
                    .limit(limit * 3)
                )
            )
            .scalars()
            .all()
        )
        seen = {o.id for _, o in scored}
        for other in more:
            if other.id in seen:
                continue
            scored.append((0, other))
            seen.add(other.id)
            if len(scored) >= limit * 2:
                break
    scored.sort(key=lambda x: (-x[0], -(x[1].rate_average or 0)))
    return {
        "items": [_work_dict(o) for _, o in scored[:limit]],
        "total": len(scored),
    }


@router.get("/works/{work_id}")
async def get_work(
    work_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    w = (await db.execute(select(AsmrWork).where(AsmrWork.id == work_id))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    d = _work_dict(w, with_details=True)
    d["is_favorite"] = await _is_favorite(db, user.id, work_id)
    return {"work": d}


async def _is_favorite(db: AsyncSession, user_id: str, work_id: str) -> bool:
    from app.models.asmr_favorite import AsmrFavorite

    return (
        await db.execute(
            select(AsmrFavorite.id).where(
                AsmrFavorite.user_id == user_id, AsmrFavorite.work_id == work_id
            )
        )
    ).scalar_one_or_none() is not None


@router.post("/works/{work_id}/favorite")
async def favorite_work(
    work_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.models.asmr_favorite import AsmrFavorite

    w = (await db.execute(select(AsmrWork.id).where(AsmrWork.id == work_id))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    exists = (
        await db.execute(
            select(AsmrFavorite.id).where(
                AsmrFavorite.user_id == user.id, AsmrFavorite.work_id == work_id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(AsmrFavorite(user_id=user.id, work_id=work_id))
        await db.commit()
        return {"ok": True, "favorite": True}
    return {"ok": True, "favorite": True}


@router.delete("/works/{work_id}/favorite")
async def unfavorite_work(
    work_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.models.asmr_favorite import AsmrFavorite

    row = (
        await db.execute(
            select(AsmrFavorite).where(
                AsmrFavorite.user_id == user.id, AsmrFavorite.work_id == work_id
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"ok": True, "favorite": False}


@router.get("/favorites")
async def list_favorites(
    page: int = Query(1, ge=1),
    # 收藏页前端一次拉全量（page_size=200），上限与前端约定对齐
    page_size: int = Query(24, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """收藏列表（按收藏时间倒序）。"""
    from app.models.asmr_favorite import AsmrFavorite

    total = (
        await db.execute(
            select(func.count()).select_from(AsmrFavorite).where(AsmrFavorite.user_id == user.id)
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(AsmrWork)
                .join(AsmrFavorite, AsmrFavorite.work_id == AsmrWork.id)
                .where(AsmrFavorite.user_id == user.id)
                .order_by(AsmrFavorite.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_work_dict(w) for w in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/stats")
async def asmr_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await asmr_ingest.stats(db)


@router.get("/disk")
async def list_disk(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """网盘资源索引（asmrgay 目录元数据）。"""
    from app.services.asmr_disk import search_disk

    return await search_disk(db, q, page=page, page_size=page_size)


@router.post("/disk/sync")
async def sync_disk(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """同步网盘资源目录索引（admin）。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可同步")
    from app.services.asmr_disk import ingest_asmrgay

    result = await ingest_asmrgay(db)
    return {"ok": True, **result}


@router.post("/sync")
async def sync_asmr(
    mode: str = Query("daily", pattern="^(full|daily)$"),
    keyword: str = "",
    update_existing: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """拉取最新元数据并幂等入库（admin）。全量首次接入用；daily 增量。

    update_existing=True：已有作品也刷新标签/评分等字段（修复历史解析问题）。
    """
    global _sync_running
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可同步")
    if _sync_running:
        raise HTTPException(status_code=409, detail="同步任务正在进行中")
    async with _sync_lock:
        _sync_running = True
        try:
            if mode == "daily":
                result = await asmr_ingest.ingest_asmr_one(
                    db, max_pages=200, keyword=keyword, update_existing=update_existing
                )
            else:
                result = await asmr_ingest.ingest_asmr_one(
                    db,
                    max_pages=asmr_ingest.MAX_PAGES,
                    keyword=keyword,
                    update_existing=update_existing,
                )
                scrapers = await asmr_ingest.ingest_from_scrapers(db)
                result["scrapers"] = scrapers
        finally:
            _sync_running = False
    # 入库后清列表查询缓存（前缀失效）
    await cache_clear_prefix("asmr:works:")
    return {"ok": True, **result}


# ===== 手动元数据编辑（MovieHub 手动匹配模式的对应物：刮削错了可以修） =====


class AsmrWorkEditRequest(BaseModel):
    """手动修正作品元数据（title/社团/分级/标签/封面）。"""

    title: str | None = Field(default=None, max_length=500)
    circle_name: str | None = Field(default=None, max_length=200)
    nsfw: bool | None = None
    tags: list[dict[str, str]] | None = None  # [{name, zh}]
    cover_url: str | None = Field(default=None, max_length=1000)


@router.put("/works/{work_id}")
async def edit_asmr_work(
    work_id: str,
    req: AsmrWorkEditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动修正元数据（刮削错误修正；修改后清列表缓存）。"""
    w = (await db.execute(select(AsmrWork).where(AsmrWork.id == work_id))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    if req.title is not None:
        w.title = req.title.strip()
    if req.circle_name is not None:
        w.circle_name = req.circle_name.strip()
    if req.nsfw is not None:
        w.nsfw = req.nsfw
    if req.tags is not None:
        w.tags = json.dumps(req.tags, ensure_ascii=False)
    if req.cover_url is not None:
        w.cover_url = req.cover_url.strip()
    await db.commit()
    await cache_clear_prefix("asmr:works")
    return {"ok": True, "work": _work_dict(w)}
