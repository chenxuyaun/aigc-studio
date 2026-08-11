"""原著蒸馏后台任务：书籍文本 → 角色档案（复用 story_tasks 双模式骨架）。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from celery import shared_task

from app.core.database import AsyncSessionLocal

# 保留后台任务引用，避免被 GC 回收。
_running: set[asyncio.Task[Any]] = set()


def _dispatch_distill(
    user_id: str,
    asset_id: str,
    doc_id: str | None = None,
    text: str | None = None,
    book_title: str | None = None,
) -> None:
    """进程内调度（默认）；USE_CELERY_WORKER=1 时投递队列。"""
    from app.core.config import settings

    if int(getattr(settings, "USE_CELERY_WORKER", 0) or 0) == 1:
        from app.tasks.celery_app import celery_app

        celery_app.send_task(
            "distill_character_task",
            args=[user_id, asset_id, doc_id, text, book_title],
        )
        return
    task = asyncio.create_task(_run_distill(user_id, asset_id, doc_id, text, book_title))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _run_distill(
    user_id: str,
    asset_id: str,
    doc_id: str | None = None,
    text: str | None = None,
    book_title: str | None = None,
) -> dict[str, Any]:
    """执行蒸馏（任务内，写 profile.status 终态）。"""
    from app.core.database import engine
    from app.services.character_distill import distill_profile

    # celery prefork + asyncio.run：dispose 连接池避免跨 loop 连接卡死
    await engine.dispose()
    # 幂等锁：同一角色卡防并发双蒸馏（双击触发/重试竞态）
    from app.core.cache import redis_lock

    if not await redis_lock(f"aigc:lock:distill:{asset_id}", ttl=1800):
        return {"ok": False, "asset_id": asset_id, "error": "蒸馏任务已在进行中"}
    async with AsyncSessionLocal() as db:
        try:
            await distill_profile(
                db, user_id, asset_id, doc_id=doc_id, text=text, book_title=book_title
            )
            return {"ok": True, "asset_id": asset_id}
        except Exception as exc:
            return {"ok": False, "asset_id": asset_id, "error": str(exc)[:300]}


def _celery_task(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """类型化 shared_task 包装：注册到默认 app，统一重试策略（DB 抖动自动重试）。"""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        import sqlalchemy

        _retryable = (sqlalchemy.exc.OperationalError, sqlalchemy.exc.TimeoutError)

        @shared_task(  # type: ignore[untyped-decorator]
            name=name,
            bind=True,
            max_retries=2,
            autoretry_for=_retryable,
            retry_backoff=True,
            retry_backoff_max=60,
            retry_jitter=True,
        )
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    return deco


@_celery_task("distill_character_task")
def distill_character_task(
    user_id: str = "",
    asset_id: str = "",
    doc_id: str | None = None,
    text: str | None = None,
    book_title: str | None = None,
) -> dict[str, Any]:  # pragma: no cover - celery
    """原著蒸馏（celery 入口）。"""
    return asyncio.run(_run_distill(user_id, asset_id, doc_id, text, book_title))
