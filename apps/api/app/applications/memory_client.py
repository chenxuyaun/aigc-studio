"""MemoryCore gateway 客户端封装（角色陪伴交互记忆 L0-L3）。

- 惰性初始化 + 5s 超时 + 异常静默降级：gateway 不可用时返回空/跳过，
  对话完全不受影响（与 cover 代理同模式）；
- 记忆隔离键：team="aigc-studio" 固定，agent=角色卡 asset_id（每角色独立），
  user=平台用户（不同用户陪同一角色记忆隔离），session=chat_id（L0/L1 按会话）；
- 客户端按 (user_id, agent_id) 缓存复用；SDK 为 vendor 拷贝（apps/api/vendor/）。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger("aigc.memory")

_TEAM_ID = "aigc-studio"
_SERVICE_ID = "default"

# (user_id, agent_id) -> AsyncMemoryClient（LRU 上限防长期运行累积）
_clients: OrderedDict[tuple[str, str], Any] = OrderedDict()
_MAX_CLIENTS = 100
_disabled = False


def _new_client(user_id: str, agent_id: str) -> Any:
    from tencentdb_agent_memory.v3 import AsyncMemoryClient

    return AsyncMemoryClient(
        endpoint=settings.TDAI_MEMORY_ENDPOINT,
        api_key=settings.TDAI_MEMORY_API_KEY,
        service_id=_SERVICE_ID,
        team_id=_TEAM_ID,
        agent_id=agent_id,
        user_id=user_id,
        timeout=5,
    )


def _client(user_id: str, agent_id: str) -> Any | None:
    global _disabled
    if _disabled or not settings.TDAI_MEMORY_ENDPOINT:
        return None
    key = (user_id, agent_id)
    client = _clients.get(key)
    if client is None:
        try:
            client = _new_client(user_id, agent_id)
            _clients[key] = client
        except Exception:
            _disabled = True  # 构造失败（缺 SDK/配置）后本进程不再尝试
            return None
    _clients.move_to_end(key)
    while len(_clients) > _MAX_CLIENTS:
        _clients.popitem(last=False)
    return client


async def _call(user_id: str, agent_id: str, method: str, *args: Any, **kwargs: Any) -> Any | None:
    """调用 gateway 方法；任何异常静默降级返回 None。"""
    client = _client(user_id, agent_id)
    if client is None:
        return None
    try:
        return await getattr(client, method)(*args, **kwargs)
    except Exception as exc:  # 网络/超时/校验错误一律降级
        logger.warning("memory_gateway_call_failed", method=method, error=str(exc)[:200])
        return None


async def memory_add_conversation(
    user_id: str,
    agent_id: str,
    chat_id: str,
    messages: list[dict[str, str]],
) -> bool:
    """L0 写入本轮对话消息（写入即触发 gateway 端 L1 抽取调度）。"""
    result = await _call(
        user_id,
        agent_id,
        "add_conversation",
        messages=messages,
        session_id=chat_id,
    )
    return result is not None


async def memory_search_atomic(
    user_id: str,
    agent_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """L1 原子记忆检索（BM25/FTS，无 embedding 时纯关键词）。"""
    result = await _call(user_id, agent_id, "search_atomic", query, limit=limit)
    if not result or not isinstance(result, dict):
        return []
    return [m for m in (result.get("items") or result.get("records") or []) if isinstance(m, dict)]


async def memory_query_atomic(
    user_id: str,
    agent_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """L1 原子记忆最近列表（检索空时的兜底召回）。"""
    result = await _call(user_id, agent_id, "query_atomic", limit=limit)
    if not result or not isinstance(result, dict):
        return []
    return [m for m in (result.get("items") or result.get("records") or []) if isinstance(m, dict)]


async def memory_list_scenarios(user_id: str, agent_id: str) -> list[dict[str, Any]]:
    """L2 场景清单（含 heat/summary，供导航注入）。"""
    result = await _call(user_id, agent_id, "list_scenarios")
    if not result or not isinstance(result, dict):
        return []
    items = result.get("items") or result.get("scenarios") or []
    return [s for s in items if isinstance(s, dict)]


async def memory_read_core(user_id: str, agent_id: str) -> str:
    """L3 交互画像（persona）。"""
    result = await _call(user_id, agent_id, "read_core")
    if not result or not isinstance(result, dict):
        return ""
    content = result.get("content") or result.get("persona") or ""
    return str(content)


async def memory_clear(user_id: str, agent_id: str, chat_id: str | None = None) -> bool:
    """清空交互记忆（L1 原子 + L2 场景 + L3 画像；可选按会话清 L0）。"""
    ok = True
    # L0：按会话删除（会话级）
    if chat_id:
        result = await _call(
            user_id, agent_id, "query_conversation", session_id=chat_id, limit=1000
        )
        ids = []
        if isinstance(result, dict):
            for m in result.get("items") or []:
                if isinstance(m, dict) and m.get("id"):
                    ids.append(str(m["id"]))
        if ids:
            await _call(
                user_id,
                agent_id,
                "delete_conversation",
                message_ids=ids,
                session_id=chat_id,
            )
    # L1：全部原子
    result = await _call(user_id, agent_id, "query_atomic", limit=1000)
    ids = []
    if isinstance(result, dict):
        for m in result.get("items") or []:
            if isinstance(m, dict) and m.get("id"):
                ids.append(str(m["id"]))
    if ids:
        await _call(user_id, agent_id, "delete_atomic", ids=ids)
    # L2：场景全部删除
    scenes = await memory_list_scenarios(user_id, agent_id)
    for s in scenes:
        path = s.get("path") or s.get("name")
        if path:
            await _call(user_id, agent_id, "rm_scenario", path=str(path))
    # L3：画像清空
    await _call(user_id, agent_id, "write_core", content="")
    return ok
