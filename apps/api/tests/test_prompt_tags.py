"""提示词标签：创建/更新标签、按标签筛选、标签列表。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_prompt_tags_crud_and_filter(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/prompts/",
        json={"title": "带标签", "content": "内容A", "tags": ["绘画", "写实"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    prompt_id = resp.json()["id"]
    assert set(resp.json()["tags"]) == {"绘画", "写实"}

    # 无标签提示词
    await client.post(
        "/api/v1/prompts/", json={"title": "无标签", "content": "内容B"}, headers=headers
    )

    # 标签列表带计数
    resp = await client.get("/api/v1/prompts/tags", headers=headers)
    assert resp.status_code == 200
    by_name = {t["name"]: t["count"] for t in resp.json()}
    assert by_name.get("绘画") == 1
    assert "写实" in by_name

    # 按标签筛选
    resp = await client.get("/api/v1/prompts/?tag=绘画", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "带标签"
    assert set(items[0]["tags"]) == {"绘画", "写实"}

    # 更新标签（清空 + 换标签）
    resp = await client.put(
        f"/api/v1/prompts/{prompt_id}",
        json={"tags": ["摄影"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["摄影"]

    resp = await client.get("/api/v1/prompts/?tag=绘画", headers=headers)
    assert resp.json()["total"] == 0
    resp = await client.get("/api/v1/prompts/?tag=摄影", headers=headers)
    assert resp.json()["total"] == 1
