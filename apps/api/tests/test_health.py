"""健康探针与依赖检查。"""

from __future__ import annotations


async def test_live(client):
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_ok(client):
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["mysql"]["status"] == "ok"


async def test_dependencies(client):
    resp = await client.get("/api/v1/health/dependencies")
    assert resp.status_code == 200
    deps = resp.json()["dependencies"]
    assert "mysql" in deps
    # 内部配置不外泄（安全修复后）
    assert "storage_provider" not in deps
    assert "r2_write_percent" not in deps


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
