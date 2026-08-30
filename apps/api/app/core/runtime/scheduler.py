"""Core Runtime - Scheduler 调度器。

从 services/task_runner.py 拆出：
- _running：后台任务引用集合（避免 GC 回收）
- schedule_media_task：从请求处理器调度一个媒体任务的后台处理
- _recover_stale_tasks：启动扫描，标记进程崩溃遗留的 processing/queued 任务为失败

P0 边界：task_runner.py 通过 `from app.core.runtime.scheduler import ...` 使用。
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.runtime.task import is_cancelled  # noqa: F401  # 保持包内引用一致
from app.models.generation_task import GenerationTask

# 保留后台任务引用，避免被 GC 回收。
_running: set[asyncio.Task[None]] = set()


def schedule_media_task(task_id: str) -> None:
    """从请求处理器调度一个媒体任务的后台处理。"""
    from app.services.task_runner import run_media_task  # 延迟 import 避免循环

    task = asyncio.create_task(run_media_task(task_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def recover_stale_tasks(max_age_seconds: int = 1800) -> None:
    """启动扫描：把进程崩溃遗留的 processing/queued 任务标记为失败，避免永久卡死。"""
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(GenerationTask).where(
                        GenerationTask.status.in_(["queued", "processing", "submitting"]),
                        GenerationTask.updated_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.status = "failed"
            r.error_message = "server_restart_timeout"
            await db.commit()
