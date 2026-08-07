"""agent 工具循环测试。"""

from __future__ import annotations

import json

import pytest
from app.providers.base import TextResult


@pytest.mark.anyio
async def test_agent_chat_runs_tools_then_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """第一轮 tool_calls → 执行工具 → 第二轮纯文本回复。"""
    from app.services import agent_chat as ac

    events: list[dict] = []

    class _FakeProvider:
        def __init__(self) -> None:
            self.round = 0

        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            self.round += 1
            if self.round == 1:
                return TextResult(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "list_tasks",
                            "arguments": json.dumps({"limit": 1}),
                        }
                    ],
                )
            return TextResult(content="完成，已查询最近任务。")

    async def fake_resolve(db: object, model: str) -> tuple[object, str]:
        return _FakeProvider(), "m"

    monkeypatch.setattr(ac, "_resolve_provider", fake_resolve)
    async def fake_call_tool(name: str, args: dict) -> str:
        return '[{"id": "t1", "status": "succeeded"}]'

    monkeypatch.setattr(ac, "_call_tool", fake_call_tool)

    messages = [{"role": "user", "content": "查任务"}]
    async for ev in ac.agent_chat_stream(messages, "m", db=None, tools=None):
        events.append(ev)

    kinds = [e["type"] for e in events]
    assert kinds == ["tool", "tool", "chunk"]
    assert events[0]["name"] == "list_tasks"
    assert events[0]["status"] == "running"
    assert events[1]["status"] == "done"
    assert events[2]["content"] == "完成，已查询最近任务。"


@pytest.mark.anyio
async def test_agent_chat_provider_error_yields_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游 503 时产出错误 chunk 而不是抛异常（前端不卡死）。"""
    from app.services import agent_chat as ac

    class _BrokenProvider:
        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            raise RuntimeError("上游返回 503: upstream_unavailable")

    async def fake_resolve(db: object, model: str) -> tuple[object, str]:
        return _BrokenProvider(), "m"

    monkeypatch.setattr(ac, "_resolve_provider", fake_resolve)
    events = [ev async for ev in ac.agent_chat_stream(
        [{"role": "user", "content": "hi"}], "m", db=None, tools=None
    )]
    assert len(events) == 1
    assert events[0]["type"] == "chunk"
    assert "503" in events[0]["content"]
