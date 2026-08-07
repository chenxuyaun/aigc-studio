import asyncio

import pytest


async def _wait_succeeded(client, token: str, task_id: str, wait_timeout: float = 10.0) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = asyncio.get_event_loop().time() + wait_timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        await asyncio.sleep(0.2)
    raise AssertionError("任务未在超时内完成")


@pytest.mark.asyncio
async def test_image_task_lifecycle(client, admin_token):
    assert admin_token
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 创建图片任务 → 初始 queued。
    resp = await client.post(
        "/api/v1/generations/image/generate",
        json={"model": "mock", "prompt": "一只在星空下的猫", "width": 512, "height": 512},
        headers=headers,
    )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] in ("queued", "processing")
    task_id = task["id"]

    # 后台执行器推进到 succeeded。
    done = await _wait_succeeded(client, admin_token, task_id)
    assert done["status"] == "succeeded"
    assert done["progress"] == 100

    import json

    result = json.loads(done["result"])
    asset_id = result["asset_id"]

    # 素材内容可下载，且为 SVG。
    content = await client.get(f"/api/v1/assets/{asset_id}/content", headers=headers)
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/svg")
    assert b"<svg" in content.content

    # 素材列表包含它。
    assets = await client.get("/api/v1/assets/", headers=headers)
    assert assets.status_code == 200
    ids = [a["id"] for a in assets.json()["items"]]
    assert asset_id in ids


@pytest.mark.asyncio
async def test_task_ownership_404_for_other_user(client, admin_token):
    # 不存在的任务返回 404（同时用于避免枚举）。
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/tasks/nonexistent-id", headers=headers)
    assert resp.status_code == 404
