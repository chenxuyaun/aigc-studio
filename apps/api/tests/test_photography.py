"""写真摄影 API 测试。"""

from __future__ import annotations

import io

import pytest


@pytest.mark.asyncio
async def test_photography_album_and_upload_flow(client, admin_token):
    assert admin_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 创建相册
    resp = await client.post(
        "/api/v1/photography/albums",
        json={
            "title": "日系清新人像",
            "description": "窗光 · 胶片感",
            "style_tags": "日系,胶片,人像",
            "is_public": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    album = resp.json()
    assert album["title"] == "日系清新人像"
    assert album["photo_count"] == 0
    album_id = album["id"]

    # 列表可见
    listed = await client.get("/api/v1/photography/albums?page=1&page_size=20", headers=headers)
    assert listed.status_code == 200
    ids = [a["id"] for a in listed.json()["items"]]
    assert album_id in ids

    # 上传一张最小 PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = [("files", ("sample.png", io.BytesIO(png_bytes), "image/png"))]
    up = await client.post(
        f"/api/v1/photography/albums/{album_id}/photos",
        headers=headers,
        files=files,
    )
    assert up.status_code == 200, up.text
    photos = up.json()
    assert len(photos) == 1
    photo_id = photos[0]["id"]
    assert photos[0]["mime_type"] == "image/png"

    # 相册 photo_count / 封面更新
    detail = await client.get(f"/api/v1/photography/albums/{album_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["photo_count"] == 1
    assert body["cover_photo_id"] == photo_id
    assert body["cover_url"]

    # 内容可下载
    content = await client.get(
        f"/api/v1/photography/photos/{photo_id}/content", headers=headers
    )
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/")
    assert content.content.startswith(b"\x89PNG")

    # 删除相册级联
    deleted = await client.delete(f"/api/v1/photography/albums/{album_id}", headers=headers)
    assert deleted.status_code == 200
    gone = await client.get(f"/api/v1/photography/albums/{album_id}", headers=headers)
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_photography_requires_auth(client):
    resp = await client.get("/api/v1/photography/albums")
    assert resp.status_code == 401
