"""MCP HTTP 端点认证测试。"""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_mcp_http_requires_auth() -> None:
    """无 token 访问 /mcp 被拒。"""
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code in (401, 403)
