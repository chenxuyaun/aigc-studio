"""角色卡市场：公开索引浏览 API。"""

import pytest


@pytest.mark.asyncio
async def test_cardmarket_list_and_search(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/cardmarket?page_size=5", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 0
    assert "items" in body

    resp = await client.get("/api/v1/cardmarket/categories", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["categories"], list)

    resp = await client.get("/api/v1/cardmarket/preview/no-such-slug", headers=headers)
    assert resp.status_code == 404

    # 未登录 401
    resp = await client.get("/api/v1/cardmarket")
    assert resp.status_code == 401
