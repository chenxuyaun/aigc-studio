import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me(client, admin_token):
    if admin_token:
        resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"
