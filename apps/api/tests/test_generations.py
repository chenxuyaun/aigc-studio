import pytest


@pytest.mark.asyncio
async def test_text_generate(client, admin_token):
    if admin_token:
        resp = await client.post(
            "/api/v1/generations/text/generate",
            json={"prompt": "hello", "stream": False},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
