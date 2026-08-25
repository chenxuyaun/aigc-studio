"""批11：社区分享墙 API 测试（走 FastAPI TestClient 风格，复用 conftest client）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _auth_headers(client) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    tok = resp.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def test_post_create_list_like_delete(client) -> None:
    h = await _auth_headers(client)

    # 发布
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "第一幅作品", "content": "赛博朋克城市夜景", "kind": "text"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # 墙上可见 + liked_by_me=False
    r = await client.get("/api/v1/community/posts?page=1&page_size=10", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    mine = next((x for x in items if x["id"] == pid), None)
    assert mine is not None and mine["title"] == "第一幅作品"
    assert mine["likes"] == 0 and mine["liked_by_me"] is False and mine["mine"] is True

    # 点赞 → likes=1 & liked_by_me=True；再点取消
    r = await client.post(f"/api/v1/community/posts/{pid}/like", headers=h)
    assert r.status_code == 200 and r.json() == {"likes": 1, "liked": True}
    r = await client.post(f"/api/v1/community/posts/{pid}/like", headers=h)
    assert r.status_code == 200 and r.json() == {"likes": 0, "liked": False}

    # 图片帖必须带 image_url
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "图帖", "kind": "image", "image_url": ""},
        headers=h,
    )
    assert r.status_code == 422

    # 作者删除
    r = await client.delete(f"/api/v1/community/posts/{pid}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    r = await client.get("/api/v1/community/posts?page=1", headers=h)
    assert all(x["id"] != pid for x in r.json()["items"])


async def test_post_validation(client) -> None:
    h = await _auth_headers(client)
    r = await client.post("/api/v1/community/posts", json={"title": ""}, headers=h)
    assert r.status_code == 422  # 标题必填


async def test_requires_auth(client) -> None:
    r = await client.get("/api/v1/community/posts")
    assert r.status_code in (401, 403)
