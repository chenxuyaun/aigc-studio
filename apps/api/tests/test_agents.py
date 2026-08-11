import pytest


@pytest.mark.asyncio
async def test_list_agents_empty(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/agents/", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_agent_crud(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # create
    resp = await client.post(
        "/api/v1/agents/",
        json={
            "name": "文案助手",
            "system_prompt": "你是一个文案专家",
            "agent_type": "generic",
            "model": "mock",
            "tools": ["search"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    agent = resp.json()
    aid = agent["id"]
    assert agent["name"] == "文案助手"
    assert agent["tools"] == ["search"]

    # get
    resp = await client.get(f"/api/v1/agents/{aid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["system_prompt"] == "你是一个文案专家"

    # list
    resp = await client.get("/api/v1/agents/", headers=headers)
    assert resp.json()["total"] == 1

    # update
    resp = await client.put(
        f"/api/v1/agents/{aid}",
        json={"name": "高级文案", "tools": ["search", "calc"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "高级文案"
    assert resp.json()["tools"] == ["search", "calc"]

    # favorite
    resp = await client.post(f"/api/v1/agents/{aid}/favorite", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["favorited"] is True

    # favorites list + ids
    resp = await client.get("/api/v1/agents/mine/favorites", headers=headers)
    assert resp.json()["total"] == 1
    resp = await client.get("/api/v1/agents/mine/favorite-ids", headers=headers)
    assert aid in resp.json()["ids"]

    # unfavorite
    resp = await client.post(f"/api/v1/agents/{aid}/favorite", headers=headers)
    assert resp.json()["favorited"] is False

    # delete
    resp = await client.delete(f"/api/v1/agents/{aid}", headers=headers)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/agents/{aid}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_search(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    for name in ("翻译助手", "总结助手"):
        await client.post(
            "/api/v1/agents/",
            json={"name": name, "system_prompt": "x"},
            headers=headers,
        )
    resp = await client.get("/api/v1/agents/?search=翻译", headers=headers)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["name"] == "翻译助手"


@pytest.mark.asyncio
async def test_agent_promote_mission_role(client, admin_token):
    """Mission 现场角色转正：source_type mission → user，agent_type mission → generic。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/agents/",
        json={
            "name": "民谣词人",
            "system_prompt": "你是民谣词人",
            "agent_type": "mission",
            "source_type": "mission",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    aid = resp.json()["id"]

    resp = await client.post(f"/api/v1/agents/{aid}/promote", headers=headers)
    assert resp.status_code == 200, resp.text
    promoted = resp.json()
    assert promoted["source_type"] == "user"
    assert promoted["agent_type"] == "generic"

    # 权限：其他用户不能转正他人的 Agent
    resp = await client.post(f"/api/v1/agents/{aid}/promote")
    assert resp.status_code in (401, 403)

    # 404
    resp = await client.post("/api/v1/agents/not-exist/promote", headers=headers)
    assert resp.status_code == 404
