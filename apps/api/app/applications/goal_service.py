"""创作目标模式（Goal Mode）执行服务。

复用 app.services.agent_chat.agent_chat_stream 的核心工具循环：
以 goal_text 构造系统提示词（先拆解计划 → 逐步调用 MCP 工具 → 成果总结），
同步消费其事件流（不转 SSE，只累积 chunk content），带超时保护。

不重构 agent_chat：它在内部自行处理 provider 解析与 MCP 工具执行，
对外就是 async generator，直接把事件流拉完即可拿到最终 content。
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.agent_chat import agent_chat_stream
from app.models.creation_goal import CreationGoal

_GOAL_RUN_TIMEOUT_SECONDS = 180.0

# 目标模式系统提示词：要求 AI 先拆解、再逐步调工具、最后总结
GOAL_SYSTEM_PROMPT = (
    "你是一名创作目标执行助手。用户会给出一个创作目标。\n"
    "请严格执行以下流程：\n"
    "1. 【拆解计划】把目标拆成 2~5 个可执行的小步骤，先说明你的执行计划；\n"
    "2. 【逐步执行】对每个需要工具的步骤，调用可用的 MCP 创作工具"
    "（如 generate_image / generate_comic / generate_text / synthesize_speech / story_forge 等）"
    "逐步完成；每步执行后检查工具返回结果；\n"
    "3. 【成果总结】全部步骤执行完后，给出最终成果总结：完成了什么、"
    "调用了哪些工具、各步产出与最终成果（含资产链接/文件信息）。\n"
    "若目标不需要调用工具即可完成，直接给出成果总结。"
)


async def run_goal(
    db: AsyncSession,
    goal: CreationGoal,
    model: str = "",
    timeout_seconds: float = _GOAL_RUN_TIMEOUT_SECONDS,
) -> CreationGoal:
    """同步跑完整个 agent 工具循环并落 goal 终态。

    - 复用 agent_chat_stream（与 SSE 路由同一执行路径）；
    - 超时保护：整段工具循环包在 asyncio.wait_for 里；
    - 状态机：running → succeeded / failed，结果写 result_summary。
    """
    goal.status = "running"
    await db.commit()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": GOAL_SYSTEM_PROMPT},
        {"role": "user", "content": goal.goal_text},
    ]

    chunks: list[str] = []

    async def _collect() -> None:
        async for ev in agent_chat_stream(messages, model, db, tools=None):
            if ev.get("type") == "chunk":
                chunks.append(str(ev.get("content") or ""))

    try:
        await asyncio.wait_for(_collect(), timeout=timeout_seconds)
    except TimeoutError:
        goal.status = "failed"
        goal.result_summary = f"（执行超时：超过 {int(timeout_seconds)} 秒）"
        await db.commit()
        await db.refresh(goal)
        return goal
    except Exception as exc:  # provider 上游异常等：agent_chat 内部已兜住大部分，这里是最后防线
        goal.status = "failed"
        goal.result_summary = f"（执行失败：{type(exc).__name__}: {str(exc)[:200]}）"
        await db.commit()
        await db.refresh(goal)
        return goal

    content = "".join(chunks).strip()
    goal.status = "succeeded" if content else "failed"
    goal.result_summary = content or "（执行完成但模型未返回内容）"
    await db.commit()
    await db.refresh(goal)
    return goal
