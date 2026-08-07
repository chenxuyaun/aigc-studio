"""Celery 任务入口。

当前媒体生成仍由进程内 asyncio task_runner 驱动（无需独立 worker 也能跑通）。
本模块把同名任务挂到 Celery，便于后续把 schedule_media_task 切换为 delay()。
Worker 启动后可手动/脚本触发，或通过 USE_CELERY_WORKER=1 走队列。

注意：任务成功 = 任务已提交执行器；执行器内部失败会在 DB 标记 failed。
Celery 层仅对临时性故障（DB 连接抖动等）自动重试，业务失败不重放已提交的生成。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

import sqlalchemy.exc

from app.tasks.celery_app import celery_app


def _run_async(coro: Awaitable[None]) -> None:
    asyncio.run(coro)


# 仅 DB 临时故障自动重试（退避 + 抖动）；其余异常直接失败
_RETRYABLE = (sqlalchemy.exc.OperationalError, sqlalchemy.exc.TimeoutError)


def _make_task(name: str) -> Callable[..., object]:
    @celery_app.task(  # type: ignore[untyped-decorator]
        bind=True,
        name=name,
        max_retries=2,
        autoretry_for=_RETRYABLE,
        retry_backoff=True,
        retry_backoff_max=120,
        retry_jitter=True,
    )
    def task(self: object, task_id: str) -> str:
        from app.services.task_runner import run_media_task

        _run_async(run_media_task(task_id))
        return task_id

    return cast(Callable[..., object], task)


generate_text_task = _make_task("generate_text")
generate_image_task = _make_task("generate_image")
generate_video_task = _make_task("generate_video")
generate_audio_task = _make_task("generate_audio")
