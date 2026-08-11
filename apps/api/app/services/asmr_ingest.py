"""ASMR 聚合采集：asmr.one 公开 API 为主源，其余站点尽力采集。

数据只含元数据（标题/标签/评分/封面链接等），不含音频本体。
asmr.one API：GET https://api.asmr.one/api/works?page=&pageSize=&keyword=
返回 {works: [...], pagination: {totalCount, ...}}。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asmr_work import AsmrWork

logger = structlog.get_logger()

ASMR_ONE_API = "https://api.asmr.one/api/works"
ASMR_ONE_SOURCE = "asmr_one"
PAGE_SIZE = 50
REQUEST_INTERVAL = 0.6  # 秒：限速防封
MAX_PAGES = 3000  # 全量上限（6.2 万条 ≈ 1248 页）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _i18n_name(v: Any, fallback: str) -> str:
    """i18n 值可能是字符串或 {name, censored} 结构，取 name。"""
    if isinstance(v, dict):
        return str(v.get("name") or fallback)
    return str(v) if v else fallback


def _parse_tags(tags: list[dict[str, Any]]) -> list[dict[str, str]]:
    """标签 → [{name, zh}]（i18n 里取中文翻译，没有则用英文/原名）。"""
    out: list[dict[str, str]] = []
    for t in tags or []:
        name = str(t.get("name") or "")
        if not name:
            continue
        i18n = t.get("i18n") or {}
        zh = (
            _i18n_name(i18n.get("zh-cn"), "")
            or _i18n_name(i18n.get("zh"), "")
            or _i18n_name(i18n.get("en-us"), "")
            or name
        )
        out.append({"name": name, "zh": zh})
    return out


def _parse_langs(editions: list[Any] | None) -> tuple[list[str], bool]:
    """语言版本 → (语言代码数组, 是否有中文版)。兼容对象与字符串两种结构。"""
    langs: list[str] = []
    for e in editions or []:
        if isinstance(e, dict):
            lang = str(e.get("lang") or "").strip()
        elif isinstance(e, str):
            lang = e.strip()
        else:
            continue
        if lang and lang not in langs:
            langs.append(lang)
    has_chinese = any(lang.startswith("CHI") or lang in ("ZHS", "ZHT", "CHT") for lang in langs)
    return langs, has_chinese


def _work_to_model(w: dict[str, Any]) -> dict[str, Any]:
    """API 作品对象 → AsmrWork 字段。"""
    vas = [str(v.get("name") or "") for v in (w.get("vas") or []) if v.get("name")]
    circle = w.get("circle") or {}
    nsfw = bool(w.get("nsfw")) or str(w.get("age_category_string") or "") == "adult"
    langs, has_chinese = _parse_langs(w.get("language_editions"))
    return {
        "source": ASMR_ONE_SOURCE,
        "source_work_id": str(w.get("source_id") or w.get("id") or ""),
        "title": str(w.get("title") or ""),
        "circle_name": str(circle.get("name") or ""),
        "price": int(w.get("price") or 0),
        "release_date": _parse_date(w.get("release")),
        "duration_seconds": int(w.get("duration") or 0),
        "rate_average": float(w.get("rate_average_2dp") or 0),
        "dl_count": int(w.get("dl_count") or 0),
        "nsfw": nsfw,
        "age_category": str(w.get("age_category_string") or ("adult" if nsfw else "general")),
        "vas": json.dumps(vas, ensure_ascii=False),
        "tags": json.dumps(_parse_tags(w.get("tags") or []), ensure_ascii=False),
        "langs": json.dumps(langs, ensure_ascii=False),
        "has_chinese": has_chinese,
        "has_subtitle": bool(w.get("has_subtitle")),
        "cover_url": str(w.get("samCoverUrl") or ""),
        "main_cover_url": str(w.get("mainCoverUrl") or w.get("samCoverUrl") or ""),
        "thumbnail_url": str(w.get("thumbnailCoverUrl") or w.get("samCoverUrl") or ""),
        "source_url": str(w.get("source_url") or ""),
    }


async def fetch_asmr_one_page(
    client: httpx.AsyncClient, page: int, keyword: str = "", page_size: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    """拉一页（含限速）。失败抛 httpx.HTTPError 由调用方处理。"""
    params: dict[str, Any] = {"page": page, "pageSize": page_size}
    if keyword:
        params["keyword"] = keyword
    resp = await client.get(ASMR_ONE_API, params=params, headers={"User-Agent": UA})
    resp.raise_for_status()
    data = resp.json()
    return data.get("works") or []


async def ingest_asmr_one(
    db: AsyncSession,
    max_pages: int = MAX_PAGES,
    keyword: str = "",
    page_size: int = PAGE_SIZE,
    update_existing: bool = False,
    start_page: int = 1,
) -> dict[str, Any]:
    """全量/关键词采集：分页拉取 → 幂等 upsert。

    update_existing=True 时对已有行也刷新可变字段（标签/评分/下载数等，
    用于修复历史解析问题或定期刷新）。
    start_page>1 时从指定页续跑（任务撞限时后断点续传）。
    """
    inserted = 0
    skipped = 0
    updated = 0
    pages = 0
    errors = 0
    last_error = ""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for page in range(start_page, max_pages + 1):
            try:
                works = await fetch_asmr_one_page(
                    client, page, keyword=keyword, page_size=page_size
                )
            except Exception as exc:  # 单页失败不中断整体采集
                errors += 1
                last_error = f"{type(exc).__name__}: {str(exc)[:150]}"
                logger.warning("asmr_page_failed", page=page, error=last_error)
                if errors >= 5:
                    break  # 连续失败说明被封/断网，停止
                await asyncio.sleep(REQUEST_INTERVAL * 3)
                continue
            if not works:
                break  # 空页 = 拉完
            pages += 1
            # 批量判重（一页一条 IN 查询，避免 6.2 万次逐条 SELECT）
            page_fields = [_work_to_model(w) for w in works]
            page_fields = [f for f in page_fields if f["source_work_id"]]
            page_ids = [f["source_work_id"] for f in page_fields]
            existing_rows: dict[str, int] = {}
            if page_ids:
                existing = await db.execute(
                    select(AsmrWork.id, AsmrWork.source_work_id).where(
                        AsmrWork.source == ASMR_ONE_SOURCE,
                        AsmrWork.source_work_id.in_(page_ids),
                    )
                )
                existing_rows = {str(swid): wid for wid, swid in existing.all()}
            for fields in page_fields:
                exists = existing_rows.get(fields["source_work_id"])
                if exists:
                    if update_existing:
                        row = (
                            await db.execute(select(AsmrWork).where(AsmrWork.id == exists))
                        ).scalar_one()
                        row.title = fields["title"]
                        row.circle_name = fields["circle_name"]
                        row.price = fields["price"]
                        row.release_date = fields["release_date"]
                        row.duration_seconds = fields["duration_seconds"]
                        row.rate_average = fields["rate_average"]
                        row.dl_count = fields["dl_count"]
                        row.nsfw = fields["nsfw"]
                        row.age_category = fields["age_category"]
                        row.vas = fields["vas"]
                        row.tags = fields["tags"]
                        row.langs = fields["langs"]
                        row.has_chinese = fields["has_chinese"]
                        row.has_subtitle = fields["has_subtitle"]
                        row.cover_url = fields["cover_url"]
                        row.main_cover_url = fields["main_cover_url"]
                        row.thumbnail_url = fields["thumbnail_url"]
                        row.source_url = fields["source_url"]
                        updated += 1
                    else:
                        skipped += 1
                    continue
                db.add(AsmrWork(**fields))
                inserted += 1
            await db.commit()
            # 进度（日志级）
            if pages % 100 == 0:
                logger.info(
                    "asmr_progress",
                    pages=pages,
                    inserted=inserted,
                    skipped=skipped,
                    updated=updated,
                )
            await asyncio.sleep(REQUEST_INTERVAL)
    return {
        "source": ASMR_ONE_SOURCE,
        "inserted": inserted,
        "skipped": skipped,
        "updated": updated,
        "pages": pages,
        "errors": errors,
        "last_error": last_error or None,
    }


async def ingest_from_scrapers(db: AsyncSession) -> dict[str, Any]:
    """其余来源尽力采集（403/JS 渲染大概率失败，失败记录不中断）。"""
    results: dict[str, Any] = {}
    targets = {
        "asmrmoon": "https://asmrmoon.com",
        "asmrgay": "https://www.asmrgay.com",
    }
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for source, url in targets.items():
            try:
                resp = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
                if resp.status_code != 200:
                    results[source] = {"status": "blocked", "http": resp.status_code}
                    continue
                # JS 渲染/未知结构：本版不做 HTML 解析，仅记录可达性
                text = resp.text[:500]
                results[source] = {
                    "status": "reachable",
                    "http": resp.status_code,
                    "sample": text[:80].replace("\n", " "),
                    "parsed": 0,
                }
            except Exception as exc:
                results[source] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                }
            await asyncio.sleep(0.5)
    return results


async def run_sync(
    db: AsyncSession,
    mode: str = "full",
    keyword: str = "",
    update_existing: bool = False,
    start_page: int = 1,
) -> dict[str, Any]:
    """全量或每日增量同步入口（任务与 API 共用）。"""
    if mode == "daily":
        # 每日增量：最近 3 天窗口内拉取（按 release_date 过滤）
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        _ = since  # 窗口留作后续过滤优化
        result = await ingest_asmr_one(
            db,
            max_pages=200,
            keyword=keyword,
            update_existing=update_existing,
            start_page=start_page,
        )
        result["mode"] = "daily"
        return result
    result = await ingest_asmr_one(
        db,
        max_pages=MAX_PAGES,
        keyword=keyword,
        update_existing=update_existing,
        start_page=start_page,
    )
    result["mode"] = "full"
    scrapers = await ingest_from_scrapers(db)
    result["scrapers"] = scrapers
    return result


async def stats(db: AsyncSession) -> dict[str, Any]:
    total = (await db.execute(select(func.count()).select_from(AsmrWork))).scalar_one()
    nsfw_count = (
        await db.execute(select(func.count()).select_from(AsmrWork).where(AsmrWork.nsfw.is_(True)))
    ).scalar_one()
    by_source = {
        source: (
            await db.execute(
                select(func.count()).select_from(AsmrWork).where(AsmrWork.source == source)
            )
        ).scalar_one()
        for source in ("asmr_one", "asmrmoon", "asmrgay")
    }
    latest = (
        await db.execute(select(func.max(AsmrWork.updated_at)).select_from(AsmrWork))
    ).scalar_one()
    return {
        "total": total,
        "nsfw_count": nsfw_count,
        "general_count": total - nsfw_count,
        "by_source": by_source,
        "last_sync_at": latest.isoformat() if latest else None,
    }
