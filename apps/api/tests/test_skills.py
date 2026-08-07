import pytest


@pytest.mark.asyncio
async def test_skill_crud(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/skills/",
        json={
            "name": "搜索技能",
            "instructions": "调用搜索引擎返回结果",
            "skill_type": "tool",
            "inputs_schema": {"query": {"type": "string"}},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]
    assert resp.json()["inputs_schema"] == {"query": {"type": "string"}}

    resp = await client.get(f"/api/v1/skills/{sid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["instructions"] == "调用搜索引擎返回结果"

    resp = await client.get("/api/v1/skills/", headers=headers)
    assert resp.json()["total"] == 1

    resp = await client.put(
        f"/api/v1/skills/{sid}",
        json={"name": "高级搜索"},
        headers=headers,
    )
    assert resp.json()["name"] == "高级搜索"

    resp = await client.delete(f"/api/v1/skills/{sid}", headers=headers)
    assert resp.status_code == 200
    assert (await client.get(f"/api/v1/skills/{sid}", headers=headers)).status_code == 404
