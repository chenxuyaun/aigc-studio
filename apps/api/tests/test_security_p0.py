"""P0 安全：projects / users / providers / task SSE 鉴权。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_projects_require_auth_and_scope(client, admin_token):
    denied = await client.get("/api/v1/projects/")
    assert denied.status_code == 401

    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/projects/",
        json={"name": "p0", "description": "sec"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    listed = await client.get("/api/v1/projects/", headers=headers)
    assert listed.status_code == 200
    assert any(p["id"] == pid for p in listed.json()["items"])

    got = await client.get(f"/api/v1/projects/{pid}", headers=headers)
    assert got.status_code == 200

    bare = await client.get(f"/api/v1/projects/{pid}")
    assert bare.status_code == 401


@pytest.mark.asyncio
async def test_users_get_requires_auth(client, admin_token):
    bare = await client.get("/api/v1/users/")
    assert bare.status_code in (401, 403)

    # 无 token 读任意 id
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    uid = me.json()["id"]
    denied = await client.get(f"/api/v1/users/{uid}")
    assert denied.status_code == 401

    ok = await client.get(
        f"/api/v1/users/{uid}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_providers_public_requires_login_and_hides_secrets(client, admin_token):
    bare = await client.get("/api/v1/providers/")
    assert bare.status_code == 401

    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/providers/",
        json={
            "name": "mock-box",
            "provider_type": "text",
            "base_url": "http://127.0.0.1:9",
            "api_key": "super-secret-key",
            "default_model": "mock",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body.get("has_api_key") is True
    assert "api_key" not in body or not body.get("api_key")
    assert "encrypted_api_key" not in body
    assert body.get("api_key_fingerprint")

    pub = await client.get("/api/v1/providers/", headers=headers)
    assert pub.status_code == 200
    for item in pub.json():
        assert "base_url" not in item
        assert "api_key" not in item
        assert "encrypted_api_key" not in item


@pytest.mark.asyncio
async def test_task_events_require_auth(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 造一个任务
    resp = await client.post(
        "/api/v1/generations/image/generate",
        json={"model": "mock", "prompt": "sse auth", "width": 128, "height": 128},
        headers=headers,
    )
    assert resp.status_code == 200
    task_id = resp.json()["id"]

    bare = await client.get(f"/api/v1/tasks/{task_id}/events")
    assert bare.status_code == 401

    # 带 token 应能建立流（读一行即可）
    async with client.stream("GET", f"/api/v1/tasks/{task_id}/events", headers=headers) as stream:
        assert stream.status_code == 200
        line = None
        async for raw in stream.aiter_lines():
            if raw:
                line = raw
                break
        assert line is not None
        assert line.startswith("data:")
