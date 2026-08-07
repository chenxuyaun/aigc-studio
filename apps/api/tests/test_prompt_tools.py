import pytest


@pytest.mark.asyncio
async def test_prompt_generate(client, admin_token):
    assert admin_token
    resp = await client.post(
        "/api/v1/generations/prompt/generate",
        json={"idea": "给咖啡店写宣传文案", "scene": "商品文案", "audience": "年轻上班族"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_prompt"]
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 3
    assert "角色" in body["full_prompt"]


@pytest.mark.asyncio
async def test_prompt_optimize(client, admin_token):
    assert admin_token
    resp = await client.post(
        "/api/v1/generations/prompt/optimize",
        json={"prompt": "写一篇文章"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert 0 <= body["score_before"] <= 100
    assert body["score_after"] >= body["score_before"]
    assert len(body["diagnosis"]) == 7
    assert body["standard"]


@pytest.mark.asyncio
async def test_prompt_tools_require_auth(client):
    resp = await client.post("/api/v1/generations/prompt/generate", json={"idea": "x"})
    assert resp.status_code == 401
