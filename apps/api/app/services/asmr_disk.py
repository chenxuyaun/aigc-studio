"""ASMR 网盘资源索引（asmrgay Alist 公开 API）：目录树元数据聚合。

只聚合目录/文件名元数据（供查找资源），不下载音频本体。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asmr_netdisk_item import AsmrNetdiskItem

logger = structlog.get_logger()

ASMRGAY_API = "https://www.asmrgay.com/api/fs/list"
ASMRGAY_SOURCE = "asmrgay"
TOP_LEVELS = ["asmr", "asmr2", "asmr3", "asmr4", "asmr5", "asmr6"]
MAX_PER_DIR = 500  # 单目录最多列出的作品
MAX_TOTAL = 20000  # 总量上限
REQUEST_INTERVAL = 0.4
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


async def _list_dir(client: httpx.AsyncClient, path: str) -> list[dict[str, Any]]:
    resp = await client.post(
        ASMRGAY_API,
        json={"path": path, "page": 1, "per_page": 100},
        headers={"User-Agent": UA},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 200:
        return []
    return data.get("data", {}).get("content") or []


def _parse_modified(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def _upsert(db: AsyncSession, path: str, item: dict[str, Any]) -> str:
    exists = (
        await db.execute(
            select(AsmrNetdiskItem.id).where(
                AsmrNetdiskItem.source == ASMRGAY_SOURCE,
                AsmrNetdiskItem.path == path,
            )
        )
    ).scalar_one_or_none()
    if exists:
        return "skip"
    db.add(
        AsmrNetdiskItem(
            source=ASMRGAY_SOURCE,
            path=path,
            name=str(item.get("name") or ""),
            size_bytes=int(item.get("size") or 0),
            is_dir=bool(item.get("is_dir")),
            modified=_parse_modified(item.get("modified")),
        )
    )
    return "insert"


async def ingest_asmrgay(db: AsyncSession) -> dict[str, Any]:
    """遍历顶层目录 → 分类/声优 → 作品文件夹，幂等 upsert。"""
    inserted = 0
    skipped = 0
    errors = 0
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for top in TOP_LEVELS:
            try:
                cats = await _list_dir(client, f"/{top}")
            except Exception as exc:  # 单个顶层失败不中断
                errors += 1
                logger.warning("asmrgay_top_failed", top=top, error=str(exc)[:100])
                await asyncio.sleep(REQUEST_INTERVAL * 3)
                continue
            for cat in cats[:MAX_PER_DIR]:
                cat_path = f"/{top}/{cat['name']}"
                res = await _upsert(db, cat_path, cat)
                inserted += res == "insert"
                skipped += res == "skip"
                # 第 2 层：作品文件夹（分类目录下的条目）
                if cat.get("is_dir"):
                    try:
                        works = await _list_dir(client, cat_path)
                    except Exception:
                        errors += 1
                        await asyncio.sleep(REQUEST_INTERVAL * 2)
                        continue
                    for w in works[:MAX_PER_DIR]:
                        w_path = f"{cat_path}/{w['name']}"
                        res2 = await _upsert(db, w_path, w)
                        inserted += res2 == "insert"
                        skipped += res2 == "skip"
                    await db.commit()
                    if inserted + skipped > MAX_TOTAL:
                        return {
                            "source": ASMRGAY_SOURCE,
                            "inserted": inserted,
                            "skipped": skipped,
                            "errors": errors,
                            "truncated": True,
                        }
                await asyncio.sleep(REQUEST_INTERVAL)
            await db.commit()
    return {
        "source": ASMRGAY_SOURCE,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "truncated": False,
    }


async def search_disk(
    db: AsyncSession, query: str, page: int = 1, page_size: int = 50
) -> dict[str, Any]:
    """按文件名/路径搜索网盘资源。"""
    stmt = select(AsmrNetdiskItem).where(AsmrNetdiskItem.source == ASMRGAY_SOURCE)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(AsmrNetdiskItem.name.like(like), AsmrNetdiskItem.path.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(AsmrNetdiskItem.is_dir.desc(), AsmrNetdiskItem.modified.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "path": r.path,
                "name": r.name,
                "size_bytes": r.size_bytes,
                "is_dir": r.is_dir,
                "modified": r.modified.isoformat() if r.modified else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }
