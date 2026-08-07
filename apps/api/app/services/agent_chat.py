"""智能体工具调用循环：model → tool_calls → 执行 MCP 工具 → 回填 → 最终回复。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _call_tool, _openai_tools
from app.providers.base import TextProvider
from app.services.provider_resolver import resolve_text_provider

_MAX_ROUNDS = 5


async def _resolve_provider(db: AsyncSession, model: str) -> tuple[TextProvider, str]:
    resolved = await resolve_text_provider(db, model)
    return resolved.provider, resolved.model  # type: ignore[return-value]


async def agent_chat_stream(
    messages: list[dict[str, Any]],
    model: str,
    db: AsyncSession,
    tools: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """工具循环 + 最终回复，产出 SSE 事件：

    - {"type": "tool", "name", "status": "running"|"done", "summary"?}
    - {"type": "chunk", "content"}
    """
    provider, resolved_model = await _resolve_provider(db, model)
    all_tools = _openai_tools()
    if tools:
        all_tools = [t for t in all_tools if t["function"]["name"] in set(tools)]

    for _ in range(_MAX_ROUNDS):
        prompt = _messages_to_prompt(messages)
        # 上游 503/断流等异常必须兜住：SSE 流一旦抛异常前端会卡死（等不到 done）
        try:
            result = await provider.generate(prompt, resolved_model, tools=all_tools or None)
        except Exception as exc:
            reason = str(exc).strip()[:200] or type(exc).__name__
            yield {
                "type": "chunk",
                "content": f"（模型调用失败：{reason}，请稍后重试或换模型）",
            }
            return
        calls = result.tool_calls or []
        if not calls:
            yield {"type": "chunk", "content": result.content}
            return
        tool_msgs: list[dict[str, Any]] = []
        for tc in calls:
            name = str(tc.get("name") or "")
            arguments = tc.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else {}
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "name": name, "status": "running"}
            out = await _call_tool(name, args if isinstance(args, dict) else {})
            yield {"type": "tool", "name": name, "status": "done", "summary": out[:200]}
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id") or ""),
                    "content": out,
                }
            )
        messages = [
            *messages,
            {"role": "assistant", "content": None, "tool_calls": calls},
            *tool_msgs,
        ]

    # 轮次上限：基于已收集的工具结果强制收尾（不传工具，让模型产出最终答案）
    try:
        final = await provider.generate(_messages_to_prompt(messages), resolved_model)
        content = final.content or "（模型未返回内容）"
    except Exception as exc:
        reason = str(exc).strip()[:200] or type(exc).__name__
        content = f"（模型调用失败：{reason}）"
    yield {"type": "chunk", "content": content}


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """结构化消息 → 单条 prompt（provider.generate 只收单条 prompt）。"""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if content:
            parts.append(f"{role}: {content}")
        elif m.get("tool_calls"):
            names = [tc.get("name") for tc in m["tool_calls"]]
            parts.append(f"{role}: (调用了工具 {names})")
        elif role == "tool":
            parts.append(f"tool({m.get('tool_call_id')}): {m.get('content')}")
    return "\n\n".join(parts)
