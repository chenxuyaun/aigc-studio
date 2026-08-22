"""Redis 查询缓存工具（优雅降级：Redis 不可用时静默跳过，不阻塞业务）。

- 惰性建连：首次 get 才建立连接；
- 连接失败后本进程禁用（_disabled），避免每个请求都撞超时（测试环境无 redis）；
- 所有异常吞掉返回 None，缓存层绝不影响主流程。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import weakref
from typing import Any

from app.core.config import settings

logger = logging.getLogger("aigc.cache")

_client: Any = None
# celery worker 每任务 asyncio.run 新事件循环：redis 异步客户端的连接池
# 同样不能跨 loop 复用（"Future attached to a different loop"）。
# API 进程单循环 → 惰性建一个共享客户端（行为不变）；worker 每循环各一个。
_loop_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    weakref.WeakKeyDictionary()
)
_disabled = False


def _new_client() -> Any:
    import redis.asyncio as aioredis

    return aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _redis() -> Any:
    global _client
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        if _client is None:
            _client = _new_client()
        return _client
    client = _loop_clients.get(loop)
    if client is None:
        client = _new_client()
        _loop_clients[loop] = client
    return client


async def cache_get(key: str) -> str | None:
    global _disabled
    if _disabled:
        return None
    try:
        return await _redis().get(key)
    except Exception:
        _disabled = True
        return None


async def cache_set(key: str, value: str, ttl: int = 600) -> None:
    if _disabled:
        return
    with contextlib.suppress(Exception):
        await _redis().set(key, value, ex=ttl)


async def cache_json_get(key: str) -> object | None:
    raw = await cache_get(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, (dict, list)) else None
    except Exception:
        return None


async def cache_json_set(key: str, value: object, ttl: int = 600) -> None:
    if _disabled:
        return
    with contextlib.suppress(Exception):
        await cache_set(key, json.dumps(value, ensure_ascii=False, default=str), ttl)


async def cache_clear_prefix(prefix: str) -> None:
    """删除某前缀的所有 key（同步/入库后使相关查询缓存失效）。"""
    if _disabled:
        return
    try:
        client = _redis()
        async for k in client.scan_iter(match=f"{prefix}*", count=500):
            await client.delete(k)
    except Exception:
        pass


async def redis_lock(key: str, ttl: int = 300) -> bool:
    """Redis SETNX 互斥锁：成功返回 True；已存在/Redis 不可用时放行（不阻塞业务）。

    用于跨进程任务互斥（celery worker + api 进程共享）：如 register_batch 防叠批次、
    run_media_task 防双执行。锁不手动释放，靠 TTL 自然过期。
    """
    if _disabled:
        return True
    try:
        client = _redis()
        ok = await client.set(key, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        return True
