"""voice 端点 + agent_chat 注入测试（LLM 全 mock，不触网）。

覆盖：GET/PUT/DELETE profile、extract（无料 ok:false）、corpus 增列、
agent_chat 有档案时 prompt 含文风注入、无档案时不含（服务层返回空串跳过）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

_FAKE_CONTENT = "好的，明白了。"


def _mk_llm_result(content: str) -> Any:
    obj = type("R", (), {})
    inst = obj()
    inst.content = content
    inst.tool_calls = None
    inst.reasoning = ""
    return inst


def _fake_resolve(seen: list[str]):
    async def _generate(prompt: str, model: str, **kw: Any) -> Any:
        seen.append(prompt)
        return _mk_llm_result(_FAKE_CONTENT)

    async def _resolve(db: object, model: str):
        provider = type("P", (), {})()
        provider.generate = _generate
        return type("R", (), {"provider": provider, "model": "mock"})()

    return _resolve


@pytest.mark.asyncio
async def test_profile_crud_flow(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 初始无档案
    r = await client.get("/api/v1/voice/profile", headers=headers)
    assert r.status_code == 200
    assert r.json()["exists"] is False

    # PUT upsert 建档
    r = await client.put(
        "/api/v1/voice/profile",
        headers=headers,
        json={
            "name": "我的口吻",
            "voice_dna": {
                "sentence_length": "short",
                "preferred": ["短句", "偶尔反问"],
                "avoid": ["套话"],
            },
            "samples": [{"title": "A", "text": "这事挺离谱的，但就这么发生了。"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["profile"]["source"] == "manual"
    assert body["profile"]["voice_dna"]["sentence_length"] == "short"

    # GET 回读
    r = await client.get("/api/v1/voice/profile", headers=headers)
    assert r.json()["profile"]["name"] == "我的口吻"

    # DELETE 停用
    r = await client.delete("/api/v1/voice/profile", headers=headers)
    assert r.json()["deleted"] == 1
    r = await client.get("/api/v1/voice/profile", headers=headers)
    assert r.json()["exists"] is False


@pytest.mark.asyncio
async def test_corpus_add_and_list(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        "/api/v1/voice/corpus",
        headers=headers,
        json={"kind": "note", "text": "这段是我的真实表达样本，用来提取文风。"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # 太短 → 422（pydantic min_length=8 校验层拦截）
    r = await client.post(
        "/api/v1/voice/corpus", headers=headers, json={"kind": "chat", "text": "短"}
    )
    assert r.status_code == 422
    r = await client.get("/api/v1/voice/corpus", headers=headers)
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "note"


@pytest.mark.asyncio
async def test_extract_no_corpus_returns_ok_false(client, admin_token) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 无档案 + 无语料 → extract ok:false
    r = await client.post("/api/v1/voice/profile/extract", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_agent_chat_injects_voice_when_profile_exists(client, user_token) -> None:
    """有 manual 档案时，发给 provider 的 prompt 应含文风档案。"""
    headers = {"Authorization": f"Bearer {user_token}"}
    r = await client.put(
        "/api/v1/voice/profile",
        headers=headers,
        json={"voice_dna": {"preferred": ["短句"], "avoid": ["套话"]}},
    )
    assert r.status_code == 200

    seen: list[str] = []
    with patch(
        "app.services.agent_chat.resolve_text_provider", side_effect=_fake_resolve(seen)
    ):
        async with client.stream(
            "POST",
            "/api/v1/generations/text/agent/chat",
            headers=headers,
            json={
                "model": "",
                "messages": [{"role": "user", "content": "帮我写一段产品介绍"}],
            },
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    assert seen, "provider 应被调用"
    assert "文风档案" in seen[0]


@pytest.mark.asyncio
async def test_agent_chat_no_profile_no_voice_in_prompt(client, user_token) -> None:
    """无档案时 agent_chat 正常，prompt 不含文风注入（服务返回空串跳过）。"""
    headers = {"Authorization": f"Bearer {user_token}"}
    seen: list[str] = []
    with patch(
        "app.services.agent_chat.resolve_text_provider", side_effect=_fake_resolve(seen)
    ):
        async with client.stream(
            "POST",
            "/api/v1/generations/text/agent/chat",
            headers=headers,
            json={"model": "", "messages": [{"role": "user", "content": "你好"}]},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    assert seen, "provider 应被调用"
    assert "文风档案" not in seen[0]
