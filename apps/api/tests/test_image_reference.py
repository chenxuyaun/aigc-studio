"""图片参考图（写真 photo / 素材 asset）契约。"""

from __future__ import annotations

import io
import json

import pytest


@pytest.mark.asyncio
async def test_image_with_reference_photo(client, admin_token):
    assert admin_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    album = (
        await client.post(
            "/api/v1/photography/albums",
            json={"title": "ref-album", "is_public": False},
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
        files=[("files", ("ref.png", io.BytesIO(png), "image/png"))],
    )
    assert up.status_code == 200, up.text
    photo_id = up.json()[0]["id"]

    resp = await client.post(
        "/api/v1/generations/image/generate",
        json={
            "model": "mock",
            "prompt": "with reference",
            "width": 256,
            "height": 256,
            "reference_photo_id": photo_id,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["id"]

    import asyncio

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
    result = json.loads(body["result"])
    assert result.get("reference_photo_id") == photo_id

    content = await client.get(f"/api/v1/assets/{result['asset_id']}/content", headers=headers)
    assert content.status_code == 200
    assert photo_id[:8].encode() in content.content or b"ref:" in content.content


@pytest.mark.asyncio
async def test_image_reference_photo_forbidden(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/generations/image/generate",
        json={
            "model": "mock",
            "prompt": "x",
            "width": 128,
            "height": 128,
            "reference_photo_id": "does-not-exist",
        },
        headers=headers,
    )
    assert resp.status_code == 400
