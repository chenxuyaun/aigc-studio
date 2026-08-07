"""provider tools 透传与 tool_calls 解析。"""

from __future__ import annotations

import json

import pytest
from app.providers.base import TextResult


def test_text_result_tool_calls_default_none() -> None:
    r = TextResult(content="ok")
    assert r.tool_calls is None


@pytest.mark.anyio
async def test_generate_with_tools_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """generate(tools=...) 请求体带 tools；响应含 tool_calls 被解析。"""
    from app.providers.openai_compatible import OpenAICompatibleTextProvider

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_comic",
                                        "arguments": json.dumps({"prompt": "猫"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> _FakeResp:
            captured["body"] = kwargs.get("json") or {}
            return _FakeResp()

    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient", lambda **k: _FakeClient()
    )
    p = OpenAICompatibleTextProvider(base_url="http://x/v1", api_key="k", default_model="m")
    tools = [{"type": "function", "function": {"name": "generate_comic", "parameters": {}}}]
    r = await p.generate("画漫画", tools=tools)
    assert captured["body"]["tools"] == tools
    assert r.tool_calls is not None
    assert r.tool_calls[0]["name"] == "generate_comic"
    assert json.loads(r.tool_calls[0]["arguments"]) == {"prompt": "猫"}
    assert r.tool_calls[0]["id"] == "call_1"


@pytest.mark.anyio
async def test_generate_without_tools_no_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """不带 tools 时请求体无 tools 字段，普通内容返回。"""
    from app.providers.openai_compatible import OpenAICompatibleTextProvider

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "你好", "tool_calls": None}}]}

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> _FakeResp:
            captured["body"] = kwargs.get("json") or {}
            return _FakeResp()

    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient", lambda **k: _FakeClient()
    )
    p = OpenAICompatibleTextProvider(base_url="http://x/v1", api_key="k", default_model="m")
    r = await p.generate("hi")
    assert "tools" not in captured["body"]
    assert r.content == "你好"
    assert r.tool_calls is None
