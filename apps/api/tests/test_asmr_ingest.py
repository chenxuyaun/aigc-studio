"""ASMR 采集服务：API 解析、幂等 upsert。"""

from __future__ import annotations

import json

import pytest
from app.models.asmr_work import AsmrWork
from app.services import asmr_ingest
from sqlalchemy import select

from tests.conftest import TestingSessionLocal

FAKE_WORK = {
    "id": "w-1",
    "source_id": "RJ999999",
    "title": "测试作品 掏耳",
    "circle": {"name": "测试社团"},
    "price": 1200,
    "release": "2026-07-01",
    "duration": 3600,
    "rate_average_2dp": 4.7,
    "dl_count": 100,
    "nsfw": False,
    "age_category_string": "general",
    "vas": [{"name": "声优A"}],
    "tags": [
        {"name": "seiri", "i18n": {"zh-cn": "掏耳", "ja-jp": "耳かき", "en-us": "ear"}},
    ],
    "has_subtitle": True,
    "samCoverUrl": "https://img.example/sam.jpg",
    "thumbnailCoverUrl": "https://img.example/thumb.jpg",
    "source_url": "https://dl.example/RJ999999",
}


def test_parse_work_fields() -> None:
    """API 作品 → 模型字段（标签中文翻译/时间解析/nsfw 推断）。"""
    fields = asmr_ingest._work_to_model(FAKE_WORK)
    assert fields["source"] == "asmr_one"
    assert fields["source_work_id"] == "RJ999999"
    assert fields["release_date"] is not None
    assert fields["rate_average"] == 4.7
    assert fields["nsfw"] is False
    assert fields["vas"] == '["声优A"]'
    tags = json.loads(fields["tags"])
    assert tags[0]["zh"] == "掏耳"
    assert fields["has_subtitle"] is True
    assert fields["cover_url"] == "https://img.example/sam.jpg"


def test_parse_tags_fallback() -> None:
    """无中文翻译时回退到英文/原名。"""
    tags = asmr_ingest._parse_tags(
        [
            {"name": "aaa", "i18n": {"en-us": "sleep"}},
            {"name": "bbb"},
        ]
    )
    assert tags[0]["zh"] == "sleep"
    assert tags[1]["zh"] == "bbb"


@pytest.mark.asyncio
async def test_ingest_idempotent(monkeypatch) -> None:
    """同一页重复采集：只插一次，后续跳过（幂等 upsert）。"""

    async def _fake_fetch(
        client: object, page: int, keyword: str = "", page_size: int = 50
    ) -> list[dict]:
        return [FAKE_WORK] if page == 1 else []

    monkeypatch.setattr(asmr_ingest, "fetch_asmr_one_page", _fake_fetch)
    monkeypatch.setattr(asmr_ingest, "REQUEST_INTERVAL", 0)

    async with TestingSessionLocal() as db:
        r1 = await asmr_ingest.ingest_asmr_one(db, max_pages=2)
        assert r1["inserted"] == 1
        assert r1["skipped"] == 0
        assert r1["pages"] == 1

        # 第二遍：全部跳过
        r2 = await asmr_ingest.ingest_asmr_one(db, max_pages=2)
        assert r2["inserted"] == 0
        assert r2["skipped"] == 1

        # 入库内容正确
        row = (
            await db.execute(select(AsmrWork).where(AsmrWork.source_work_id == "RJ999999"))
        ).scalar_one()
        assert row.title == "测试作品 掏耳"
        assert row.rate_average == 4.7


@pytest.mark.asyncio
async def test_ingest_stops_on_empty_pages(monkeypatch) -> None:
    """空页即结束，不无限拉取。"""

    async def _empty(
        client: object, page: int, keyword: str = "", page_size: int = 50
    ) -> list[dict]:
        return []

    monkeypatch.setattr(asmr_ingest, "fetch_asmr_one_page", _empty)
    monkeypatch.setattr(asmr_ingest, "REQUEST_INTERVAL", 0)

    async with TestingSessionLocal() as db:
        r = await asmr_ingest.ingest_asmr_one(db, max_pages=500)
        assert r["inserted"] == 0
        assert r["pages"] == 0


@pytest.mark.asyncio
async def test_scrapers_report_without_crash(monkeypatch) -> None:
    """尽力采集器失败不抛异常，返回状态记录。"""

    async def _boom(
        client: object, url: str, headers: object | None = None,
        follow_redirects: bool = True,
    ) -> object:
        raise TimeoutError("blocked")

    monkeypatch.setattr(asmr_ingest.httpx, "Timeout", lambda *a, **k: None)
    monkeypatch.setattr(asmr_ingest.httpx, "AsyncClient", lambda *a, **k: _FakeCtx(_boom))

    class _FakeCtx:
        def __init__(self, get):
            self._get = get

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url: str, **kw):
            return await self._get(self, url, **kw)

    async with TestingSessionLocal() as db:
        results = await asmr_ingest.ingest_from_scrapers(db)
        assert results["asmrmoon"]["status"] == "error"
        assert results["asmrgay"]["status"] == "error"
