"""智能体工具调用循环：model → tool_calls → 执行 MCP 工具 → 回填 → 最终回复。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.provider_resolver import resolve_text_provider
from app.mcp.server import _call_tool, _openai_tools
from app.providers.base import TextProvider

_MAX_ROUNDS = 5


async def _resolve_provider(db: AsyncSession, model: str) -> tuple[TextProvider, str]:
    resolved = await resolve_text_provider(db, model)
    return resolved.provider, resolved.model  # type: ignore[return-value]


async def agent_chat_stream(
    messages: list[dict[str, Any]],
    model: str,
    db: AsyncSession,
    tools: list[str] | None = None,
    context_blocks: list[dict[str, Any]] | None = None,
    user_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """工具循环 + 最终回复，产出 SSE 事件：

    - {"type": "tool", "name", "status": "running"|"done", "summary"?}
    - {"type": "chunk", "content"}
    - {"type": "reasoning", "content"}   # v2 批7：思维链（上游给才有）

    context_blocks（saiOS v2 P1 @ 引用真注入）：[{type,title,content}]，
    会被结构化注入提示词头部，模型可实际读到引用资源的内容。
    批8+9：user_id 非空时把该用户的长期记忆注入 system prompt。
    """
    provider, resolved_model = await _resolve_provider(db, model)
    all_tools = _openai_tools()
    if tools:
        all_tools = [t for t in all_tools if t["function"]["name"] in set(tools)]

    # 批8+9：长期记忆注入（「AI 记得你」）——失败静默，绝不影响对话
    if user_id:
        try:
            from app.applications.growth_service import build_memory_injection

            memory_text = await build_memory_injection(db, user_id)
            if memory_text:
                messages = [{"role": "system", "content": memory_text}, *messages]
        except Exception:
            pass

    # @引用内容 → 系统级上下文块（放在对话消息之前，明确标注来源）
    if context_blocks:
        ref_parts = [
            f"【引用·{b.get('type') or '资料'!s}】{str(b.get('title') or '').strip()}\n"
            + str(b.get("content") or "").strip()[:6000]
            for b in context_blocks[:10]
        ]
        ref_text = "\n\n".join(p for p in ref_parts if p.strip())
        if ref_text:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "以下是用户在输入框中 @ 引用的资料原文，回答时优先依据这些内容：\n\n"
                        + ref_text
                    ),
                },
                *messages,
            ]

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
        # v2 批7：思维链透传——上游给 reasoning 就先发（前端折叠展示「思考过程」）
        if result.reasoning:
            yield {"type": "reasoning", "content": result.reasoning}
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
            # 工具终态：summary 供前端展示一行状态；result_data 传完整结构化结果（如生图 asset_url）
            try:
                result_data = json.loads(out) if isinstance(out, str) else out
            except (json.JSONDecodeError, TypeError):
                result_data = out
            yield {
                "type": "tool",
                "name": name,
                "status": "done",
                "summary": out[:200],
                "result_data": result_data,
            }
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
