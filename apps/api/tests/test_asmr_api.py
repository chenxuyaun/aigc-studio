"""ASMR 聚合 API：列表/搜索/标签/分级过滤/排序/详情/统计。"""

from __future__ import annotations

import json

import pytest
from app.models.asmr_work import AsmrWork

from tests.conftest import TestingSessionLocal


async def _seed_works() -> None:
    from datetime import UTC, datetime, timedelta

    async with TestingSessionLocal() as db:
        base = datetime(2026, 6, 1, tzinfo=UTC)
        db.add_all([
            AsmrWork(
                id="w1", source="asmr_one", source_work_id="RJ100001",
                title="掏耳治愈系 ASMR", circle_name="CANDY VOICE",
                price=1100, release_date=base + timedelta(days=1),
                duration_seconds=7200, rate_average=4.8, dl_count=5000,
                nsfw=False, age_category="general",
                vas=json.dumps(["东山奈央"], ensure_ascii=False),
                tags=json.dumps(
                    [{"name": "掏耳", "zh": "掏耳"}, {"name": "ASMR", "zh": "ASMR"}],
                    ensure_ascii=False,
                ),
                langs='["JPN"]', has_chinese=False,
                cover_url="https://img.example/1.jpg",
            ),
            AsmrWork(
                id="w2", source="asmr_one", source_work_id="RJ100002",
                title="舔耳娇喘合集", circle_name="ルルイエエリジウム",
                price=1500, release_date=base + timedelta(days=2),
                duration_seconds=5400, rate_average=4.5, dl_count=9000,
                nsfw=True, age_category="adult",
                vas=json.dumps(["伊倉える"], ensure_ascii=False),
                tags=json.dumps([{"name": "舔耳", "zh": "舔耳"}], ensure_ascii=False),
                langs='["JPN", "CHI_HANS"]', has_chinese=True,
                cover_url="https://img.example/2.jpg",
            ),
            AsmrWork(
                id="w3", source="asmr_one", source_work_id="RJ100003",
                title="雨声助眠白噪音", circle_name="Studio 雨音",
                price=880, release_date=base + timedelta(days=3),
                duration_seconds=10800, rate_average=4.9, dl_count=12000,
                nsfw=False, age_category="general",
                vas=json.dumps([]),
                tags=json.dumps([{"name": "助眠", "zh": "助眠"}], ensure_ascii=False),
                langs='["ENG"]', has_chinese=False,
                cover_url="https://img.example/3.jpg",
            ),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_list_works_pagination_and_sort(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()

    r = await client.get("/api/v1/asmr/works", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    # 按评分排序：雨声(4.9) 最前
    r = await client.get("/api/v1/asmr/works", params={"sort": "rate"}, headers=headers)
    assert r.json()["items"][0]["title"] == "雨声助眠白噪音"

    # 分页
    r = await client.get("/api/v1/asmr/works", params={"page": 1, "page_size": 2}, headers=headers)
    assert len(r.json()["items"]) == 2
    assert r.json()["pages"] == 2


@pytest.mark.asyncio
async def test_search_and_filters(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()

    # 关键词搜标题/社团/声优
    r = await client.get("/api/v1/asmr/works", params={"q": "掏耳"}, headers=headers)
    assert r.json()["total"] == 1
    r = await client.get("/api/v1/asmr/works", params={"q": "东山奈央"}, headers=headers)
    assert r.json()["total"] == 1
    r = await client.get("/api/v1/asmr/works", params={"q": "CANDY"}, headers=headers)
    assert r.json()["total"] == 1

    # 标签过滤（中文）
    r = await client.get("/api/v1/asmr/works", params={"tag": "舔耳"}, headers=headers)
    assert r.json()["total"] == 1

    # nsfw 过滤
    r = await client.get("/api/v1/asmr/works", params={"nsfw": "general"}, headers=headers)
    assert r.json()["total"] == 2
    assert all(not i["nsfw"] for i in r.json()["items"])
    r = await client.get("/api/v1/asmr/works", params={"nsfw": "adult"}, headers=headers)
    assert r.json()["total"] == 1
    assert all(i["nsfw"] for i in r.json()["items"])


@pytest.mark.asyncio
async def test_lang_filter(client, admin_token) -> None:
    """语言过滤：中文版/日文/英文。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()

    r = await client.get("/api/v1/asmr/works", params={"lang": "zh"}, headers=headers)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["has_chinese"] is True

    r = await client.get("/api/v1/asmr/works", params={"lang": "jp"}, headers=headers)
    assert r.json()["total"] == 2

    r = await client.get("/api/v1/asmr/works", params={"lang": "en"}, headers=headers)
    assert r.json()["total"] == 1
    assert "ENG" in r.json()["items"][0]["langs"]


@pytest.mark.asyncio
async def test_work_detail_and_stats(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()

    r = await client.get("/api/v1/asmr/works/w1", headers=headers)
    assert r.status_code == 200
    work = r.json()["work"]
    assert work["source_work_id"] == "RJ100001"
    assert work["vas"] == ["东山奈央"]
    assert work["tags"][0]["zh"] == "掏耳"

    r = await client.get("/api/v1/asmr/works/nonexistent", headers=headers)
    assert r.status_code == 404

    r = await client.get("/api/v1/asmr/stats", headers=headers)
    assert r.json()["total"] == 3
    assert r.json()["by_source"]["asmr_one"] == 3


@pytest.mark.asyncio
async def test_sync_requires_admin(client, admin_token, user_token) -> None:
    """非管理员同步返回 403。"""
    r = await client.post(
        "/api/v1/asmr/sync",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_favorite_flow(client, admin_token) -> None:
    """收藏 → 列表 → 取消收藏。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()

    r = await client.post("/api/v1/asmr/works/w1/favorite", headers=headers)
    assert r.status_code == 200
    assert r.json()["favorite"] is True

    r = await client.get("/api/v1/asmr/favorites", headers=headers)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == "w1"

    # 详情带 is_favorite
    r = await client.get("/api/v1/asmr/works/w1", headers=headers)
    assert r.json()["work"]["is_favorite"] is True

    r = await client.delete("/api/v1/asmr/works/w1/favorite", headers=headers)
    assert r.status_code == 200
    assert r.json()["favorite"] is False
    r = await client.get("/api/v1/asmr/favorites", headers=headers)
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_similar_works(client, admin_token) -> None:
    """相似作品按标签重叠返回；无重叠时补最近发布（不返回空）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()
    # w1 标签：掏耳/ASMR；同分级（全年龄）内 w3 标签无重叠 → 补最近发布（w3）
    r = await client.get("/api/v1/asmr/works/w1/similar", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "w3"
    # 成人作品（w2）不会被推荐给全年龄作品
    assert all(i["id"] != "w2" for i in body["items"])


@pytest.mark.asyncio
async def test_global_search_includes_asmr(client, admin_token) -> None:
    """全局搜索含 asmr scope。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _seed_works()
    r = await client.get("/api/v1/search", params={"q": "掏耳"}, headers=headers)
    assert r.status_code == 200
    scopes = {i["scope"] for i in r.json()["items"]}
    assert "asmr" in scopes
