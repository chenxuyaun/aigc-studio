import pytest


@pytest.mark.asyncio
async def test_list_prompts(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/prompts/", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_prompt(client, admin_token):
    if admin_token:
        resp = await client.post(
            "/api/v1/prompts/",
            json={"title": "Test", "content": "Hello"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
