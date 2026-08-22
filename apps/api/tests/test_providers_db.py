"""Provider 目录与 API（P2 只读语义）。

deprecation-plan.md P2：写操作（POST/PUT/DELETE/import-env）→ 410；
GET catalog/admin 与 POST /{id}/test 探测保留。
"""

from __future__ import annotations

import pytest


async def _seed_provider(base_url: str, *, model: str = "m", priority: int = 9) -> str:
    """绕过已下线的写 API，直接在测试库种一条 ProviderConfig。"""
    from app.models.provider_config import ProviderConfig
    from app.security.ownership import seal_secret
    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        row = ProviderConfig(
            name=f"Seed {base_url}",
            provider_type="openai_compatible",
            base_url=base_url,
            default_model=model,
            is_enabled=True,
            priority=priority,
            encrypted_api_key=seal_secret("k"),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


@pytest.mark.asyncio
async def test_write_ops_gone(client, admin_token):
    """P2：全部写操作返回 410 Gone 并指引模型中心。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    r1 = await client.post(
        "/api/v1/providers/",
        json={"name": "X", "provider_type": "openai_compatible", "base_url": "http://x/v1"},
        headers=headers,
    )
    assert r1.status_code == 410
    # 全局异常处理器会包装 error body，这里只断言指引文案存在
    assert "模型中心" in r1.text

    r2 = await client.post("/api/v1/providers/import-env", headers=headers)
    assert r2.status_code == 410

    pid = await _seed_provider("http://127.0.0.1:1/v1")
    r3 = await client.put(f"/api/v1/providers/{pid}", json={"name": "Y"}, headers=headers)
    assert r3.status_code == 410

    r4 = await client.delete(f"/api/v1/providers/{pid}", headers=headers)
    assert r4.status_code == 410


@pytest.mark.asyncio
async def test_admin_list_and_catalog_readonly(client, admin_token):
    """GET /admin 与 /catalog 保留；目录不含离线 mock，不泄露 base_url/api_key。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    pid = await _seed_provider("http://127.0.0.1:8090/v1", model="grok-4.5", priority=1)

    admin_list = await client.get("/api/v1/providers/admin", headers=headers)
    assert admin_list.status_code == 200
    assert any(p["id"] == pid for p in admin_list.json())

    catalog = await client.get("/api/v1/providers/catalog", headers=headers)
    assert catalog.status_code == 200
    ids = [c["id"] for c in catalog.json()]
    assert "mock" not in ids
    for c in catalog.json():
        assert "base_url" not in c
        assert "api_key" not in c


@pytest.mark.asyncio
async def test_provider_test_endpoint(client, admin_token):
    """POST /providers/{id}/test 保留：不可达返回 ok:false；均不 500。"""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1) 空 base_url → ok:false
    pid_empty = await _seed_provider("", model="m")
    r = await client.post(f"/api/v1/providers/{pid_empty}/test", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False

    # 2) 不可达地址 → ok:false, message 含原因
    pid_dead = await _seed_provider("http://127.0.0.1:1/v1", model="nope")
    r2 = await client.post(f"/api/v1/providers/{pid_dead}/test", headers=headers)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is False
    assert "models" in body and isinstance(body["models"], list)

    # 3) 404：不存在
    r3 = await client.post("/api/v1/providers/does-not-exist/test", headers=headers)
    assert r3.status_code == 404
