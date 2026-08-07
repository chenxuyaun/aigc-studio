"""Provider 目录与文本解析。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_provider_crud_and_catalog(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/providers/",
        json={
            "name": "Local Grok",
            "provider_type": "openai_compatible",
            "base_url": "http://127.0.0.1:8090/v1",
            "api_key": "none",
            "default_model": "grok-4.5",
            "priority": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    assert created.json()["has_api_key"] is True

    admin_list = await client.get("/api/v1/providers/admin", headers=headers)
    assert admin_list.status_code == 200
    assert any(p["id"] == pid for p in admin_list.json())

    catalog = await client.get("/api/v1/providers/catalog", headers=headers)
    assert catalog.status_code == 200
    ids = [c["id"] for c in catalog.json()]
    # 目录不含离线 mock（生产无假数据路径）
    assert "mock" not in ids
    assert pid in ids
    for c in catalog.json():
        assert "base_url" not in c
        assert "api_key" not in c


@pytest.mark.asyncio
async def test_text_generate_failure_reports_error(client, admin_token, monkeypatch):
    """配置一个不可达 base_url：任务标记 failed 并返回错误，不降级假数据、不 500。"""
    # 本测试验证真实解析链路：恢复被 conftest autouse fake 替换的 resolver
    import app.api.v1.generations.text as text_mod
    from app.services.provider_resolver import resolve_text_provider as real_resolve

    monkeypatch.setattr(text_mod, "resolve_text_provider", real_resolve)

    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/providers/",
        json={
            "name": "Dead",
            "provider_type": "openai_compatible",
            "base_url": "http://127.0.0.1:1",
            "api_key": "x",
            "default_model": "nope",
            "priority": 1,
        },
        headers=headers,
    )
    pid = created.json()["id"]
    resp = await client.post(
        "/api/v1/generations/text/generate",
        json={"model": pid, "prompt": "hi", "stream": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    # 上游不可达 → 明确 error（不产生 mock 内容）
    assert data.get("error")
    assert data["model"]  # 解析到的模型名（id 匹配时用 default_model）
