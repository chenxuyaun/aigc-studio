"""OpenAI 兼容网关测试。"""

from __future__ import annotations

import pytest
from app.providers.base import TextResult


@pytest.mark.anyio
async def test_route_by_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """model 前缀路由：grok* → grok2api，gpt-oss* → cpa。"""
    from app.api.v1 import openai_gateway as gw

    routed: list[str] = []

    class _FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            routed.append(f"{self.name}:{model}")
            return TextResult(content="hi", model=model, provider=self.name)

    async def fake_providers(db: object) -> dict[str, object]:
        return {"grok": _FakeProvider("grok"), "cpa": _FakeProvider("cpa")}

    monkeypatch.setattr(gw, "_providers", fake_providers)
    out = await gw._route_chat(
        {"model": "grok-chat-fast", "messages": [{"role": "user", "content": "hi"}]}, None
    )
    assert routed == ["grok:grok-chat-fast"]
    assert out["choices"][0]["message"]["content"] == "hi"

    out2 = await gw._route_chat(
        {"model": "gpt-oss-120b-medium", "messages": [{"role": "user", "content": "hi"}]}, None
    )
    assert routed[-1] == "cpa:gpt-oss-120b-medium"
    assert out2["object"] == "chat.completion"


@pytest.mark.anyio
async def test_route_unknown_model_goes_cpa(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 grok 前缀模型路由到 cpa（cpa 上游校验模型名）。"""
    from app.api.v1 import openai_gateway as gw

    routed: list[str] = []

    class _FakeProvider:
        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            routed.append(model)
            return TextResult(content="ok", model=model)

    async def fake_providers(db: object) -> dict[str, object]:
        return {"grok": _FakeProvider(), "cpa": _FakeProvider()}

    monkeypatch.setattr(gw, "_providers", fake_providers)
    out = await gw._route_chat({"model": "nope-model", "messages": []}, None)
    assert routed == ["nope-model"]
    assert out["choices"][0]["message"]["content"] == "ok"


@pytest.mark.anyio
async def test_route_upstream_error_openai_style(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游失败 → OpenAI 风格错误（upstream_error）。"""
    from app.api.v1 import openai_gateway as gw

    class _BrokenProvider:
        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            raise RuntimeError("上游 503")

    async def fake_providers(db: object) -> dict[str, object]:
        return {"grok": _BrokenProvider(), "cpa": _BrokenProvider()}

    monkeypatch.setattr(gw, "_providers", fake_providers)
    out = await gw._route_chat({"model": "gpt-oss-x", "messages": []}, None)
    assert "error" in out
    assert out["error"]["code"] == "upstream_error"


def test_gateway_requires_auth() -> None:
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert r.status_code in (401, 403)
