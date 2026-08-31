"""Core Runtime - 定时创作（Scheduled Creations）。

从 services/schedule_service.py 抽离：
- compute_next_run_at: daily / interval 下次执行时刻
- enqueue_run: 单条调度入队为 GenerationTask
- run_due_schedules: scan + 入队 + 推进（beat tick 入口）
- _run_text_task: text 路径同步执行（特殊，与 image/audio 不同）

P0 边界：app.services.schedule_service 保留 facade。
"""
from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.runtime.audit import log_call
from app.models.generation_task import GenerationTask
from app.models.scheduled_creation import ScheduledCreation
from app.schemas.generation import AudioGenerationRequest, ImageGenerationRequest

# 固定 Asia/Shanghai = UTC+8（中国无夏令时，无需 zoneinfo/tzdata 依赖）
_CN_TZ = timezone(timedelta(hours=8))


def compute_next_run_at(
    schedule_type: str,
    daily_time: time | None,
    interval_hours: int | None,
    now: datetime | None = None,
) -> datetime:
    """按调度类型计算下一次执行时刻（UTC aware）。

    daily：下一个 HH:MM（Asia/Shanghai 固定 UTC+8）；interval：now + interval_hours。
    """
    now = now or datetime.now(UTC)
    if schedule_type == "daily":
        if daily_time is None:
            raise ValueError("schedule_type=daily 时必须提供 daily_time (HH:MM)")
        # 服务器本地时区按 Asia/Shanghai 处理（固定 +8 无夏令时）
        now_cn = now.astimezone(_CN_TZ)
        candidate = datetime.combine(now_cn.date(), daily_time, tzinfo=_CN_TZ)
        if candidate <= now_cn:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)
    if schedule_type == "interval":
        if not interval_hours or interval_hours <= 0:
            raise ValueError("schedule_type=interval 时必须提供 interval_hours>0")
        return now + timedelta(hours=interval_hours)
    raise ValueError(f"不支持的 schedule_type: {schedule_type}")


def _media_request_for(task_type: str, prompt: str) -> Any:
    """构造与 generations 路由一致的参数模型（供 create_media_task 序列化）。"""
    if task_type == "image":
        return ImageGenerationRequest(prompt=prompt)
    if task_type == "audio":
        return AudioGenerationRequest(text=prompt)
    raise ValueError(f"不支持的 task_type: {task_type}")


async def _run_text_task(
    db: AsyncSession, task: GenerationTask, prompt: str
) -> None:
    """文本任务同步执行（复用 text.py 的非流式生成路径：resolve → provider.generate → 落库）。"""
    from app.core.runtime.model.resolver import resolve_text_provider

    resolved = await resolve_text_provider(db, task.model or "")
    provider, model = resolved.provider, resolved.model
    error_message = ""
    content = ""
    try:
        result = await provider.generate(prompt, model)
        content = result.content
    except Exception as exc:
        # 上游失败不降级假数据：错误原样上报
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
    task.status = "failed" if error_message else "succeeded"
    task.result = content
    task.model = model
    if error_message:
        task.error_message = error_message
    task.progress = 100
    task.completed_at = datetime.now(UTC)
    await db.commit()
    with contextlib.suppress(Exception):  # 调用日志失败不影响主流程
        await log_call(
            task_id=task.id,
            task_type="text",
            provider=resolved.source,
            model=model,
            status="failed" if error_message else "succeeded",
            error_message=error_message,
            duration_ms=0,
            db=db,
        )


async def enqueue_run(db: AsyncSession, schedule: ScheduledCreation) -> GenerationTask:
    """把一条调度立即入队为生成任务，返回任务记录。

    - text：创建任务后同步执行生成（run_media_task 不支持 text，与 text.py 行为一致）
    - image / audio：复用 create_media_task（进程内调度或 Celery 队列）
    """
    prompt = schedule.prompt
    task_type = schedule.task_type
    if task_type == "text":
        task = GenerationTask(
            task_type="text",
            status="processing",
            model=settings.DEFAULT_TEXT_PROVIDER or "",
            params=json.dumps({"prompt": prompt}, ensure_ascii=False),
            user_id=schedule.user_id,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        await _run_text_task(db, task, prompt)
        return task

    params = _media_request_for(task_type, prompt)
    model = (
        settings.DEFAULT_IMAGE_PROVIDER
        if task_type == "image"
        else settings.DEFAULT_SPEECH_PROVIDER
    ) or ""
    # 延迟 import 避免 task_lifecycle <-> scheduler 循环
    from app.core.runtime.task_lifecycle import create_media_task
    return await create_media_task(
        db, user_id=schedule.user_id, task_type=task_type, model=model, params=params
    )


async def run_due_schedules(
    db: AsyncSession, now: datetime | None = None
) -> dict[str, int]:
    """扫描到期调度并逐个入队（供 beat tick 调用）。

    注意：v1 只处理单实例部署——多 worker/多 beat 并发扫描时可能重复入队
    （无跨进程互斥锁）。如需多实例请加 redis SETNX 锁（参考 serial_tick 的 redis_lock）。
    """
    now = now or datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(ScheduledCreation).where(
                    ScheduledCreation.is_enabled.is_(True),
                    ScheduledCreation.next_run_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    ran = 0
    errored = 0
    for s in rows:
        try:
            task = await enqueue_run(db, s)
            s.last_run_at = now
            s.last_result_task_id = task.id
            s.last_error = None
            ran += 1
        except Exception as exc:
            s.last_error = str(exc)[:500]
            errored += 1
        # 无论成败都要推进下次执行时间，避免同一调度被反复重试/刷屏
        try:
            s.next_run_at = compute_next_run_at(
                s.schedule_type, s.daily_time, s.interval_hours, now=now
            )
        except Exception:
            # 配置异常时退避一天，防止死循环
            s.next_run_at = now + timedelta(days=1)
        await db.commit()
    return {"ran": ran, "errored": errored, "due": len(rows)}
