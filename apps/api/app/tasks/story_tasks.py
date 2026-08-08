"""Story Forge 后台任务：章节生成（任务化）+ 自动连载 tick（beat）。

双模式与媒体任务一致：
- 进程内（默认）：asyncio.create_task 后台执行（API 进程内）
- Celery（USE_CELERY_WORKER=1）：send_task 投递 text 队列

连载：celery beat 每分钟触发 serial_tick，扫描到期调度创建章节任务。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.generation_task import GenerationTask
from app.models.serial_schedule import SerialSchedule
from app.models.story_chapter import StoryChapter
from app.services import story_forge

# 保留后台任务引用，避免被 GC 回收。
_running: set[asyncio.Task[Any]] = set()


def _dispatch_story(task_id: str) -> None:
    """进程内调度（默认）；USE_CELERY_WORKER=1 时投递队列。"""
    if int(getattr(settings, "USE_CELERY_WORKER", 0) or 0) == 1:
        from app.tasks.celery_app import celery_app

        celery_app.send_task("generate_chapter_task", args=[task_id])
        return
    task = asyncio.create_task(_run_chapter_task(task_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _reset_pool_for_loop() -> None:
    """重置异步引擎连接池（celery prefork + asyncio.run 兼容）。

    每个 celery 任务里 asyncio.run 会创建新事件循环；若连接池残留
    上一个 loop 创建的 aiomysql 连接，复用时会 Future attached to a
    different loop 卡死（占用 worker 进程 → 任务池耗尽）。
    任务开头 dispose 一次，让当前 loop 重新建立连接。
    """
    from app.core.database import engine

    await engine.dispose()


async def _run_chapter_task(task_id: str) -> dict[str, Any]:
    """执行章节生成任务并写终态（仿 register_batch._update_task 模式）。"""
    await _reset_pool_for_loop()
    async with AsyncSessionLocal() as db:
        task = await db.get(GenerationTask, task_id)
        if task is None or task.status in ("succeeded", "failed", "cancelled"):
            return {"error": "任务不存在或已结束"}
        params = json.loads(task.params or "{}")
        task.status = "processing"
        task.progress = 10
        await db.commit()
        try:
            if params.get("mode") == "script":
                result = await story_forge.generate_chapter_script(
                    db,
                    task.user_id,
                    str(params.get("project_id") or ""),
                    str(params.get("chapter_id") or ""),
                    rounds=int(params.get("rounds") or 6),
                    model=task.model,
                )
            else:
                result = await story_forge.generate_chapter(
                    db,
                    task.user_id,
                    str(params.get("project_id") or ""),
                    str(params.get("chapter_id") or ""),
                    model=task.model,
                    instruction=str(params.get("instruction") or ""),
                    tool_loop=bool(params.get("tool_loop")),
                )
            if "error" in result:
                task.status = "failed"
                task.error_message = str(result["error"])[:500]
            else:
                task.status = "succeeded"
                task.progress = 100
                task.result = json.dumps({**result, "kind": "story"}, ensure_ascii=False)
            task.completed_at = datetime.now(UTC)
            await db.commit()
            return result
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)[:500]
            task.completed_at = datetime.now(UTC)
            await db.commit()
            return {"error": str(exc)[:200]}


async def _run_serial_tick() -> dict[str, Any]:
    """扫描到期连载调度：为每个调度创建下一章生成任务并推进 next_run_at。"""
    # 跨进程互斥：beat 双发/多 worker 时防重复建章
    from app.core.cache import redis_lock

    if not await redis_lock("aigc:lock:serial_tick", ttl=50):
        return {"ok": False, "error": "已有 tick 运行中，本次跳过"}
    await _reset_pool_for_loop()
    async with AsyncSessionLocal() as db:
        now = datetime.now(UTC)
        schedules = (
            await db.execute(
                select(SerialSchedule).where(
                    SerialSchedule.status == "active",
                    SerialSchedule.next_run_at <= now,
                )
            )
        ).scalars().all()
        created = 0
        skipped = 0
        for s in schedules:
            try:
                # 上一章未完成则跳过本 tick（避免并发重复生成）
                rows = (
                    await db.execute(
                        select(StoryChapter)
                        .where(StoryChapter.project_id == s.project_id)
                        .order_by(StoryChapter.chapter_no.desc())
                    )
                ).scalars().all()
                if rows and rows[0].status != "done":
                    skipped += 1
                    s.next_run_at = now + timedelta(minutes=s.interval_minutes)
                    await db.commit()
                    continue
                for _ in range(max(1, s.batch_size)):
                    chapter = await story_forge.create_chapter(
                        db, s.user_id, s.project_id
                    )
                    task = GenerationTask(
                        id=str(uuid.uuid4()),
                        task_type="chapter",
                        status="queued",
                        model="",
                        params=json.dumps(
                            {
                                "project_id": s.project_id,
                                "chapter_id": chapter.id,
                                "mode": s.mode,
                            },
                            ensure_ascii=False,
                        ),
                        user_id=s.user_id,
                    )
                    db.add(task)
                    chapter.task_id = task.id
                    s.chapter_count += 1
                    await db.commit()
                    await db.refresh(task)
                    _dispatch_story(task.id)
                    created += 1
                s.last_run_at = now
                s.error_message = ""
                s.fail_count = 0
                # 基于当前时间推进，避免任务积压时追平
                s.next_run_at = now + timedelta(minutes=s.interval_minutes)
                await db.commit()
            except Exception as exc:
                s.error_message = str(exc)[:300]
                s.fail_count = int(s.fail_count or 0) + 1
                if s.fail_count >= 3:
                    # 连续失败 3 次自动暂停，避免死循环刷失败任务
                    s.status = "paused"
                    s.error_message = f"连续失败 {s.fail_count} 次已自动暂停：{str(exc)[:200]}"
                s.next_run_at = now + timedelta(minutes=s.interval_minutes)
                await db.commit()
        return {"created": created, "skipped": skipped, "active": len(schedules)}


# ==== Celery 任务（worker 模式） ====
# shared_task：惰性注册到默认 app，避免模块级 import celery_app 触发 broker 连接
# （测试环境无 redis 时会重试 20 次拖垮用例）


def _celery_task(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """类型化 shared_task 包装：注册到默认 app，统一重试策略（DB 抖动自动重试）。"""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        import sqlalchemy

        _retryable = (sqlalchemy.exc.OperationalError, sqlalchemy.exc.TimeoutError)

        @shared_task(  # type: ignore[untyped-decorator]
            name=name, bind=True, max_retries=2, autoretry_for=_retryable,
            retry_backoff=True, retry_backoff_max=60, retry_jitter=True,
        )
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    return deco


@_celery_task("generate_chapter_task")
def generate_chapter_task(task_id: str = "") -> dict[str, Any]:  # pragma: no cover - celery
    """后台章节生成（celery 入口）。"""
    return asyncio.run(_run_chapter_task(task_id))


@_celery_task("serial_tick")
def serial_tick() -> dict[str, Any]:  # pragma: no cover - celery
    """连载 tick（celery beat 入口，每分钟）。"""
    return asyncio.run(_run_serial_tick())


# ==== 队列排空（pull 模式兜底） ====
# 实测 kombu send_task 在 uvicorn（运行中的 asyncio loop）环境下消息会静默丢失，
# 导致任务永远 queued。为此 worker 周期性扫描 DB 中 queued 任务直接执行：
# send_task 成功时任务会被置 processing（drain 跳过），消息丢失时由 drain 兜底执行。

@_celery_task("drain_queued_tasks")
def drain_queued_tasks() -> dict[str, Any]:  # pragma: no cover - celery
    """排空 queued 任务（celery beat 入口，每 15 秒）。"""
    return asyncio.run(_run_drain())


async def _run_drain() -> dict[str, Any]:
    """扫描待执行的生成任务并执行（pull 模式兜底）。

    - queued：原子抢占为 processing 后执行（防并发重复）
    - processing 且 5 分钟未更新：视为上次执行中断，抢占后重新执行
    chapter 走 story 执行器；媒体（image/video/audio/text）走 task_runner。
    """
    from datetime import timedelta as _td

    from sqlalchemy import update as sa_update

    from app.services.task_runner import run_media_task

    await _reset_pool_for_loop()
    processed = 0
    claimed = 0
    async with AsyncSessionLocal() as db:
        now = datetime.now(UTC)
        stale_before = now - _td(minutes=5)
        rows = (
            await db.execute(
                select(GenerationTask)
                .where(
                    (GenerationTask.status == "queued")
                    | (
                        (GenerationTask.status == "processing")
                        & (GenerationTask.updated_at < stale_before)
                    )
                )
                .order_by(GenerationTask.created_at.asc())
                .limit(10)
            )
        ).scalars().all()
        for t in rows:
            # 原子抢占：只抢 still queued / 超时 processing 的任务
            claimed_row = await db.execute(
                sa_update(GenerationTask)
                .where(
                    GenerationTask.id == t.id,
                    GenerationTask.status.in_(["queued", "processing"]),
                    GenerationTask.updated_at <= t.updated_at,
                )
                .values(status="processing", updated_at=now)
            )
            claimed_count = int(getattr(claimed_row, "rowcount", 0))
            if claimed_count != 1:
                continue
            await db.commit()
            claimed += 1
            try:
                if t.task_type == "chapter":
                    await _run_chapter_task(t.id)
                elif t.task_type == "register":
                    # register 由注册机执行器处理（进程内/beat 调度），
                    # drain 不能当媒体任务跑（否则 run_media_task 报"暂无真实 Provider"）
                    import json as _json

                    from app.tasks.register_batch import _execute_and_update

                    params = _json.loads(t.params or "{}")
                    await _execute_and_update(t.id, int(params.get("run_count") or 10))
                else:
                    await run_media_task(t.id)
                processed += 1
            except Exception as exc:
                t2 = await db.get(GenerationTask, t.id)
                if t2 is not None:
                    t2.status = "failed"
                    t2.error_message = f"drain 执行失败：{str(exc)[:300]}"
                    t2.completed_at = now
                    await db.commit()
    return {"processed": processed, "claimed": claimed, "scanned": len(rows)}
