"""Core Runtime - Scheduler 基础调度器（原 scheduler.py 单文件内容）。

从 services/task_runner.py 拆出（P0-1）: _running / schedule_media_task / recover_stale_tasks / _delay
P0-8 整合: 原单文件移到子包 _base.py（避免与 scheduled_creator 同名冲突）。
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.runtime.task import is_cancelled
from app.models.generation_task import GenerationTask
from sqlalchemy import select

_running: set[asyncio.Task[None]] = set()


def schedule_media_task(task_id: str) -> None:
    from app.services.task_runner import run_media_task
    task = asyncio.create_task(run_media_task(task_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _delay() -> None:
    await asyncio.sleep(max(settings.MOCK_PROVIDER_DELAY_MIN_MS, 50) / 1000)


async def recover_stale_tasks(max_age_seconds: int = 1800) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.status.in_(["queued", "processing", "submitting"]),
                    GenerationTask.updated_at < cutoff,
                )
            )
        ).scalars().all()
        for r in rows:
            r.status = "failed"
            r.error_message = "server_restart_timeout"
            await db.commit()
