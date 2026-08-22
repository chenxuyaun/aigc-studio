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


@pytest.mark.asyncio
async def test_auto_login_disabled(client):
    """AUTO_LOGIN_KEY 为空 → 404（功能关闭）。"""
    from app.core.config import settings

    settings.AUTO_LOGIN_KEY = ""
    resp = await client.post("/api/v1/auth/auto-login", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_auto_login_wrong_key(client):
    """密钥不匹配 → 403。"""
    from app.core.config import settings

    settings.AUTO_LOGIN_KEY = "test-secret-key"
    settings.AUTO_LOGIN_USERNAME = "admin"
    resp = await client.post(
        "/api/v1/auth/auto-login", json={}, headers={"X-Auto-Login-Key": "wrong"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_auto_login_success(client):
    """密钥匹配 → 200 返回 token，且 /auth/me 可用。"""
    from app.core.config import settings

    settings.AUTO_LOGIN_KEY = "test-secret-key"
    settings.AUTO_LOGIN_USERNAME = "admin"
    resp = await client.post(
        "/api/v1/auth/auto-login", json={}, headers={"X-Auto-Login-Key": "test-secret-key"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data and "refresh_token" in data
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
