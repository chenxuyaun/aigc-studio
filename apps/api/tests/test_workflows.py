import pytest


@pytest.mark.asyncio
async def test_workflow_crud(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/workflows/",
        json={
            "name": "内容生产流",
            "description": "选题→大纲→正文",
            "graph": {"nodes": [{"id": "1", "type": "skill"}], "edges": []},
            "workflow_type": "sequential",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    wf = resp.json()
    wid = wf["id"]
    assert wf["graph"]["nodes"][0]["id"] == "1"
    assert wf["version"] == 1

    resp = await client.get(f"/api/v1/workflows/{wid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "选题→大纲→正文"

    resp = await client.get("/api/v1/workflows/", headers=headers)
    # seed 会预置「推理小说工作坊」模板，总数 >= 1
    assert resp.json()["total"] >= 1

    # update graph bumps version
    resp = await client.put(
        f"/api/v1/workflows/{wid}",
        json={"graph": {"nodes": [{"id": "1"}, {"id": "2"}], "edges": []}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    # favorite
    resp = await client.post(f"/api/v1/workflows/{wid}/favorite", headers=headers)
    assert resp.json()["favorited"] is True
    resp = await client.get("/api/v1/workflows/mine/favorites", headers=headers)
    assert resp.json()["total"] == 1

    resp = await client.delete(f"/api/v1/workflows/{wid}", headers=headers)
    assert resp.status_code == 200
