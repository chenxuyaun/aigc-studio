import pytest


async def _first_prompt_id(client, token: str) -> str:
    resp = await client.get(
        "/api/v1/prompts/?page=1&page_size=1", headers={"Authorization": f"Bearer {token}"}
    )
    return resp.json()["items"][0]["id"]


@pytest.mark.asyncio
async def test_favorite_toggle_and_list(client, admin_token):
    assert admin_token
    h = {"Authorization": f"Bearer {admin_token}"}
    pid = await _first_prompt_id(client, admin_token)

    # 收藏
    r1 = await client.post(f"/api/v1/prompts/{pid}/favorite", headers=h)
    assert r1.status_code == 200
    assert r1.json()["favorited"] is True

    ids = (await client.get("/api/v1/prompts/mine/favorite-ids", headers=h)).json()["ids"]
    assert pid in ids

    favs = (await client.get("/api/v1/prompts/mine/favorites", headers=h)).json()
    assert favs["total"] >= 1
    assert pid in [p["id"] for p in favs["items"]]

    # 取消收藏
    r2 = await client.post(f"/api/v1/prompts/{pid}/favorite", headers=h)
    assert r2.json()["favorited"] is False
    ids2 = (await client.get("/api/v1/prompts/mine/favorite-ids", headers=h)).json()["ids"]
    assert pid not in ids2


@pytest.mark.asyncio
async def test_favorite_requires_auth(client):
    resp = await client.get("/api/v1/prompts/mine/favorites")
    assert resp.status_code == 401
