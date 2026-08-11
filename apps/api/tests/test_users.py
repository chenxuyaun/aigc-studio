"""用户管理：管理员创建/启停用，权限隔离。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_admin_creates_user_and_login(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/users/",
        json={"username": "newbie", "email": "newbie@test.local", "password": "pass1234"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    assert resp.json()["role"] == "user"

    # 新用户可登录
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "newbie", "password": "pass1234"}
    )
    assert resp.status_code == 200

    # 列表可见
    resp = await client.get("/api/v1/users/", headers=headers)
    assert any(u["username"] == "newbie" for u in resp.json())

    # 停用后登录被拒
    resp = await client.put(f"/api/v1/users/{user_id}", json={"is_active": False}, headers=headers)
    assert resp.status_code == 200
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "newbie", "password": "pass1234"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_manage(client, admin_token, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    resp = await client.post(
        "/api/v1/users/",
        json={"username": "hacker", "email": "h@x.local", "password": "pass1234"},
        headers=headers,
    )
    assert resp.status_code in (401, 403)
    resp = await client.get("/api/v1/users/", headers=headers)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_duplicate_username_conflict(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/users/",
        json={"username": "admin", "email": "x@x.local", "password": "pass1234"},
        headers=headers,
    )
    assert resp.status_code == 409
