"""统一本地搜索：多 scope 打分、权限过滤、snippet 生成。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_global_search_across_scopes(client, admin_token) -> None:
    """一个查询跨 scope 命中（知识库/章节/提示词/Agent）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 造数据：知识库文档 + 章节 + 提示词 + Agent
    r = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "本格推理指南", "content": "本格推理注重公平性与逻辑严密性。"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/v1/story/projects",
        json={"title": "密室谜案", "genre": "推理", "synopsis": "雨夜别墅中的密室杀人案。"},
        headers=headers,
    )
    pid = r.json()["project"]["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters",
        json={"title": "第一章 密室", "outline": "发现尸体，密室形成"},
        headers=headers,
    )

    await client.post(
        "/api/v1/prompts/",
        json={"title": "密室设计提示词", "content": "设计一个无法解释的密室"},
        headers=headers,
    )
    await client.post(
        "/api/v1/agents/",
        json={
            "name": "推理助手",
            "description": "擅长密室推理的助手",
            "system_prompt": "你是一名推理顾问",
        },
        headers=headers,
    )

    r = await client.get("/api/v1/search", params={"q": "密室"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    scopes = {i["scope"] for i in body["items"]}
    assert "story" in scopes
    assert "prompts" in scopes
    assert "agents" in scopes
    # 命中项按分数降序，含 snippet
    first = body["items"][0]
    assert first["title"]
    assert first["score"] > 0
    assert "密室" in (first["title"] + first["snippet"])


@pytest.mark.asyncio
async def test_search_knowledge_scope_only(client, admin_token) -> None:
    """scope 过滤只返回指定类型。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "时间表规范", "content": "死亡时间精确到分钟是推理小说的铁律。"},
        headers=headers,
    )
    r = await client.get(
        "/api/v1/search", params={"q": "时间表", "scope": "knowledge"}, headers=headers
    )
    assert r.status_code == 200
    assert all(i["scope"] == "knowledge" for i in r.json()["items"])
    assert r.json()["total"] >= 1

    r = await client.get(
        "/api/v1/search", params={"q": "时间表", "scope": "agents"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_search_isolates_users(client, admin_token, user_token) -> None:
    """普通用户搜不到 admin 的私有数据。"""
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    user_h = {"Authorization": f"Bearer {user_token}"}
    await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "绝密设定", "content": "只有管理员知道的秘密设定"},
        headers=admin_h,
    )
    r = await client.get(
        "/api/v1/search", params={"q": "绝密设定"}, headers=user_h
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # admin 自己能搜到
    r = await client.get(
        "/api/v1/search", params={"q": "绝密设定"}, headers=admin_h
    )
    assert r.json()["total"] >= 1


@pytest.mark.asyncio
async def test_search_empty_and_unknown_scope(client, admin_token) -> None:
    """空查询返回空；未知 scope 报 400。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = await client.get("/api/v1/search", params={"q": ""}, headers=headers)
    assert r.status_code == 422  # min_length=1

    r = await client.get(
        "/api/v1/search", params={"q": "x", "scope": "nope"}, headers=headers
    )
    assert r.status_code == 400
