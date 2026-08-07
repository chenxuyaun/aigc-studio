# ruff: noqa: PT018

"""Story Forge API 测试：项目/章节/角色/大纲/团队/连载/导出/任务化/越权。"""

from __future__ import annotations

import asyncio

import pytest


async def _create_project(client, token: str, **kw) -> dict:
    body = {"title": "晨星山物语", "genre": "奇幻", "synopsis": "少女与黑猫的冒险", **kw}
    r = await client.post(
        "/api/v1/story/projects", json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]


# ==== 项目 CRUD ====

@pytest.mark.anyio
async def test_project_crud_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    p = await _create_project(client, admin_token)
    pid = p["id"]
    assert p["status"] == "drafting" and p["genre"] == "奇幻"

    r = await client.get("/api/v1/story/projects", headers=h)
    assert len(r.json()["items"]) >= 1

    r = await client.put(
        f"/api/v1/story/projects/{pid}", json={"status": "ongoing"},
        headers=h,
    )
    assert r.json()["project"]["status"] == "ongoing"

    r = await client.get(f"/api/v1/story/projects/{pid}", headers=h)
    assert r.json()["project"]["title"] == "晨星山物语"

    # 404
    r = await client.get("/api/v1/story/projects/nope", headers=h)
    assert r.status_code == 404

    # 越权：普通用户看不到 admin 项目
    user_h = {"Authorization": f"Bearer {await _user_token(client)}"}
    r = await client.get(f"/api/v1/story/projects/{pid}", headers=user_h)
    assert r.status_code == 404

    r = await client.delete(f"/api/v1/story/projects/{pid}", headers=h)
    assert r.json()["ok"] is True


async def _user_token(client) -> str:
    from app.core.security import hash_password
    from app.models.user import User

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        session.add(
            User(
                username="storyuser",
                email="storyuser@test.local",
                password_hash=hash_password("story123"),
                role="user",
            )
        )
        await session.commit()
    r = await client.post(
        "/api/v1/auth/login", json={"username": "storyuser", "password": "story123"}
    )
    return r.json()["access_token"]


# ==== 章节 + 角色实例 ====

@pytest.mark.anyio
async def test_chapters_and_characters_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]

    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters",
        json={"title": "启程", "outline": "出发"},
        headers=h,
    )
    cid = r.json()["chapter"]["id"]
    assert r.json()["chapter"]["chapter_no"] == 1

    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters", json={"title": "山腰"}, headers=h
    )
    assert r.json()["chapter"]["chapter_no"] == 2

    r = await client.put(
        f"/api/v1/story/chapters/{cid}", json={"content": "正文片段"}, headers=h
    )
    assert r.json()["chapter"]["status"] == "done"
    assert r.json()["chapter"]["word_count"] == 4

    r = await client.get(f"/api/v1/story/projects/{pid}/chapters", headers=h)
    assert len(r.json()["items"]) == 2

    # 角色实例
    r = await client.post(
        f"/api/v1/story/projects/{pid}/characters",
        json={"name": "露娜", "role": "protagonist", "skill_ids": []},
        headers=h,
    )
    scid = r.json()["character"]["id"]
    r = await client.put(
        f"/api/v1/story/characters/{scid}",
        json={"current_state": "在山顶"},
        headers=h,
    )
    assert r.json()["character"]["current_state"] == "在山顶"

    # bible 聚合
    r = await client.get(f"/api/v1/story/projects/{pid}/bible", headers=h)
    body = r.json()
    assert len(body["chapters"]) == 2 and len(body["characters"]) == 1

    # 删除章节
    r = await client.delete(f"/api/v1/story/chapters/{cid}", headers=h)
    assert r.json()["ok"] is True

    # 清理
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 生成（mock provider 路径：无角色卡 → 400 友好错误） ====

@pytest.mark.anyio
async def test_generate_chapter_without_cards(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters", json={"title": "第一章"}, headers=h
    )
    cid = r.json()["chapter"]["id"]
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/generate",
        json={"project_id": pid, "mode": "narrative"},
        headers=h,
    )
    assert r.status_code == 400
    assert "角色卡" in r.json()["error"]["message"]
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/generate",
        json={"project_id": pid, "mode": "script"},
        headers=h,
    )
    assert r.status_code == 400
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 大纲 ====

@pytest.mark.anyio
async def test_outline_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/outline",
        params={"chapters": 3, "model": "mock"},
        headers=h,
    )
    # 大纲只需要梗概（角色卡非必需）：显式 mock provider 直接产出
    assert r.status_code == 200
    assert len(r.json()["chapters"]) == 3
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 创作团队 ====

@pytest.mark.anyio
async def test_crew_director_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/crew",
        json={"project_id": pid, "stage": "director", "model": "mock"},
        headers=h,
    )
    # 无角色卡也能跑 director（bible 为空文本兜底，mock provider 返回内容）
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json()["stage"] == "director"
    r = await client.post(
        f"/api/v1/story/projects/{pid}/crew",
        json={"project_id": pid, "stage": "unknown"},
        headers=h,
    )
    assert r.status_code == 400
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 任务化 ====

@pytest.mark.anyio
async def test_generate_chapter_task_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters", json={"title": "第一章"}, headers=h
    )
    cid = r.json()["chapter"]["id"]
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/generate/task",
        json={"project_id": pid, "mode": "narrative", "model": "mock"},
        headers=h,
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["id"]
    # 任务化会进后台（_dispatch_story → create_task）→ 无卡时任务应失败且不 500
    # 轮询终态（进程内执行很快）
    status = "queued"
    for _ in range(20):
        r = await client.get(f"/api/v1/tasks/{task_id}", headers=h)
        status = r.json().get("status") or (r.json().get("data") or {}).get("status", "")
        if status in ("succeeded", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert status in ("succeeded", "failed")
    # 失败原因应为无角色卡（mock 路径下任务执行器捕获错误写 failed）
    if status == "failed":
        err = r.json().get("error_message") or (r.json().get("data") or {}).get("error_message", "")
        assert "角色卡" in err
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 连载调度 ====

@pytest.mark.anyio
async def test_schedules_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/schedules",
        json={"interval_minutes": 30, "mode": "narrative"},
        headers=h,
    )
    assert r.status_code == 200
    sid = r.json()["schedule"]["id"]
    r = await client.get(f"/api/v1/story/projects/{pid}/schedules", headers=h)
    assert len(r.json()["items"]) == 1
    r = await client.put(
        f"/api/v1/story/schedules/{sid}",
        json={"interval_minutes": 60, "batch_size": 2, "mode": "script", "status": "paused"},
        headers=h,
    )
    assert r.json()["ok"] is True
    r = await client.delete(f"/api/v1/story/schedules/{sid}", headers=h)
    assert r.json()["ok"] is True
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 导出 ====

@pytest.mark.anyio
async def test_export_api(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters",
        json={"title": "启程", "content": "正文"},
        headers=h,
    )
    assert r.status_code == 200
    r = await client.get(
        f"/api/v1/story/projects/{pid}/export", params={"format": "markdown"}, headers=h
    )
    assert r.status_code == 200 and "# 晨星山物语" in r.text
    r = await client.get(
        f"/api/v1/story/projects/{pid}/export", params={"format": "jsonl"}, headers=h
    )
    assert r.status_code == 200 and r.headers.get("content-disposition", "").endswith(".jsonl")
    r = await client.get(
        f"/api/v1/story/projects/{pid}/export", params={"format": "epub"}, headers=h
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/epub+zip")
    assert r.content[:4] == b"PK"  # zip 魔数
    r = await client.get(
        f"/api/v1/story/projects/{pid}/export", params={"format": "pdf"}, headers=h
    )
    assert r.status_code == 422  # 非法格式
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)


# ==== 世界书项目作用域 ====

@pytest.mark.anyio
async def test_lore_project_scope(client, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = (await _create_project(client, admin_token))["id"]
    r = await client.post(
        "/api/v1/roleplay/lore",
        json={
            "content": "晨星山由星辉凝结而成",
            "keywords": ["晨星山"],
            "project_id": pid,
            "selective": True,
        },
        headers=h,
    )
    assert r.status_code == 200
    r = await client.get(f"/api/v1/roleplay/lore?project_id={pid}", headers=h)
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["project_id"] == pid
    # 不带 project 过滤看不到项目条目
    r = await client.get("/api/v1/roleplay/lore", headers=h)
    assert all(i.get("project_id") != pid for i in r.json()["items"])
    await client.delete(f"/api/v1/story/projects/{pid}", headers=h)
