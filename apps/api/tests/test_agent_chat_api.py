"""agent chat 端点测试。"""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_agent_chat_requires_auth() -> None:
    r = client.post(
        "/api/v1/generations/text/agent/chat",
        json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code in (401, 403)
