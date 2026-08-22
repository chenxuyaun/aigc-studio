"""定时创作（Scheduled Creations）后台 tick（celery beat 入口）。

跟随 serial_tick 先例：celery beat 每分钟触发 scheduled_creation_tick，
扫描 is_enabled=1 且 next_run_at<=now 的定时创作，逐条入队生成任务并推进下次时间。
单实例部署（README/compose 均为 worker -B 单 beat），v1 不引入跨 worker 互斥锁。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from celery import shared_task

logger = logging.getLogger("aigc.schedule_tick")


async def _run_schedule_tick(now: Any = None) -> dict[str, Any]:
    """扫描到期定时创作并入队（无 now 参数用当前时间）。"""
    from app.core.database import AsyncSessionLocal
    from app.services.schedule_service import run_due_schedules

    async with AsyncSessionLocal() as db:
        return await run_due_schedules(db, now=now)


def _celery_task(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """类型化 shared_task 包装（同 story_tasks 的写法）。"""

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


@_celery_task("scheduled_creation_tick")
def scheduled_creation_tick() -> dict[str, Any]:  # pragma: no cover - celery beat 入口
    """定时创作 tick（celery beat 每分钟）。"""
    return asyncio.run(_run_schedule_tick())
