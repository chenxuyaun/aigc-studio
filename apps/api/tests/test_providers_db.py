"""Provider 目录与 API（P3 终态语义）。

provider_configs 表已删除：目录只来自模型中心（+env 兜底）；
全部写/管理端点 → 410 Gone。
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_write_and_admin_ops_gone(client, admin_token):
    """P2/P3：全部写与管理端点返回 410 Gone 并指引模型中心。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    r1 = await client.post(
        "/api/v1/providers/",
        json={"name": "X", "provider_type": "openai_compatible", "base_url": "http://x/v1"},
        headers=headers,
    )
    assert r1.status_code == 410
    assert "模型中心" in r1.text

    assert (await client.post("/api/v1/providers/import-env", headers=headers)).status_code == 410
    assert (await client.get("/api/v1/providers/admin", headers=headers)).status_code == 410
    assert (
        await client.post("/api/v1/providers/some-id/test", headers=headers)
    ).status_code == 410
    assert (
        await client.put("/api/v1/providers/some-id", json={"name": "Y"}, headers=headers)
    ).status_code == 410
    assert (
        await client.delete("/api/v1/providers/some-id", headers=headers)
    ).status_code == 410


@pytest.mark.asyncio
async def test_catalog_readonly_no_secret_fields(client, admin_token):
    """GET /catalog 保留：无 mock 假数据路径，不泄露 base_url/api_key。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    catalog = await client.get("/api/v1/providers/catalog", headers=headers)
    assert catalog.status_code == 200
    ids = [c["id"] for c in catalog.json()]
    assert "mock" not in ids
    for c in catalog.json():
        assert "base_url" not in c
        assert "api_key" not in c
        assert c.get("source") in ("hub", "env")
