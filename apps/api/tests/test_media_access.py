"""媒体 access-url 与 storage_backend 契约。"""

from __future__ import annotations

import io

import pytest


@pytest.mark.asyncio
async def test_asset_access_url_and_backend(client, admin_token):
    assert admin_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 创建图片任务拿 asset
    resp = await client.post(
        "/api/v1/generations/image/generate",
        json={"model": "mock", "prompt": "access url test", "width": 256, "height": 256},
        headers=headers,
    )
    assert resp.status_code == 200
    task_id = resp.json()["id"]

    import asyncio
    import json

    deadline = asyncio.get_event_loop().time() + 10
    body = None
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        body = r.json()
        if body["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.2)
    assert body, "任务未在超时内完成"
    assert body["status"] == "succeeded"
    asset_id = json.loads(body["result"])["asset_id"]

    access = await client.get(f"/api/v1/assets/{asset_id}/access-url", headers=headers)
    assert access.status_code == 200
    payload = access.json()
    assert "url" in payload
    assert "expires_at" in payload
    # local：url 指向 content
    assert "content" in payload["url"] or payload["url"].startswith("http")

    listed = await client.get("/api/v1/assets/?page=1&page_size=5", headers=headers)
    assert listed.status_code == 200
    item = next(a for a in listed.json()["items"] if a["id"] == asset_id)
    assert item.get("storage_backend") == "local"
    assert item.get("access_url_endpoint")


@pytest.mark.asyncio
async def test_photo_access_url_requires_auth(client, admin_token):
    assert admin_token
    headers = {"Authorization": f"Bearer {admin_token}"}
    album = (
        await client.post(
            "/api/v1/photography/albums",
            json={"title": "access", "is_public": False},
            headers=headers,
        )
    ).json()
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up = await client.post(
        f"/api/v1/photography/albums/{album['id']}/photos",
        headers=headers,
        files=[("files", ("a.png", io.BytesIO(png), "image/png"))],
    )
    assert up.status_code == 200, up.text
    photo_id = up.json()[0]["id"]
    assert up.json()[0].get("storage_backend") == "local"
    assert up.json()[0].get("width", 0) >= 1

    denied = await client.get(f"/api/v1/photography/photos/{photo_id}/access-url")
    assert denied.status_code == 401

    ok = await client.get(f"/api/v1/photography/photos/{photo_id}/access-url", headers=headers)
    assert ok.status_code == 200
    assert "url" in ok.json()
