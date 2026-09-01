"""进程内媒体任务执行器（Comic Facade + 委派入口）。

P0 重构后的角色：
- **非 Comic 路径**：完全委派给 `app.core.runtime.orchestrator.run_media_task_main`。
- **Comic 路径**：通过 `app.core.runtime.comic_bridge` 间接调 Comic 业务
  （P4-2 已归位 `app/applications/comic/bridge.py`）。
- 进程内串行锁 + redis_lock 防双执行：保留在 task_runner.py（Core 设施）。

⚠️ P0 边界：task_runner.py **不**再有旧的 _media_candidates / _build_image_provider /
_try_real_media / _load_reference_image / _download_media / _ext_from_mime /
_rewrite_media_url / _upstream_model_id / _provider_kwargs 实现 — 全部在
`app.core.runtime.*`（candidate / executor / asset_writer）。
"""
from __future__ import annotations

import asyncio
import json
import weakref
from datetime import UTC, datetime
from typing import cast

import structlog
from sqlalchemy import select

from app.applications.call_logger import log_call
from app.applications.comic.bridge import (
    _comic_real_media,
    _write_comic_subassets,
)
from app.core.config import settings  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.runtime.asset_writer import write_main_asset_and_finalize
from app.core.runtime.governance import notify_event
from app.core.runtime.task import (
    is_cancelled,
)
from app.models.generation_task import GenerationTask

logger = structlog.get_logger()


# 进程内串行锁（背景：测试库为内存 SQLite 单连接，并发写会概率性失败）。
_media_exec_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _media_lock() -> asyncio.Lock:
    """按事件循环惰性创建。"""
    loop = asyncio.get_running_loop()
    lock = _media_exec_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _media_exec_locks[loop] = lock
    return lock


async def _recover_stale_tasks(max_age_seconds: int = 1800) -> None:
    """启动扫描：把进程崩溃遗留的 processing/queued 任务标记为失败，避免永久卡死。

    P0 拆分 task_runner 时曾误丢此函数（main.py lifespan 启动恢复静默失效），
    2026-09-01 从 pre-refactor-v1 原样恢复；app.main 仍从 task_runner 导入。
    """
    from datetime import UTC as _UTC
    from datetime import datetime, timedelta

    cutoff = datetime.now(_UTC) - timedelta(seconds=max_age_seconds)
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
        for row in rows:
            row.status = "failed"
            row.error_message = "服务重启导致任务中断，请重新生成"
            row.completed_at = datetime.now(_UTC)
            logger.warning("stale_task_recovered", task_id=row.id, task_type=row.task_type)
        if rows:
            await db.commit()
            logger.info("recovered_stale_tasks", count=len(rows))


async def _run_comic_task(task_id: str) -> None:
    """Comic 任务：分镜→逐格出图→拼合（所有 Comic 业务在 core.runtime.comic_bridge）。"""
    from app.core.runtime.orchestrator import _progress_loop, _resolve_model_name

    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if task is None or task.status not in ("queued", "submitting", "processing"):
            return

        try:
            params: dict[str, object] = json.loads(task.params or "{}")
            prompt = str(params.get("prompt") or params.get("text") or "")

            model_name = _resolve_model_name(task)
            use_real = bool(model_name and model_name != "mock")
            if not use_real and model_name != "mock":
                raise RuntimeError(
                    f"未配置可用的{task.task_type} Provider，请在「模型配置」中启用真实模型"
                )

            # P0-2 修复：设 processing 之前先检查 cancel（避免竞态覆盖 cancelled 状态）
            if await is_cancelled(db, task_id):
                logger.info("media_task_cancelled, task_id=%s, stage=%s", task_id, "before_processing")
                return

            task.status = "processing"
            await db.commit()

            await _progress_loop(db, task, task_id)

            render_params = {
                k: v for k, v in params.items() if k not in ("prompt", "text", "model")
            }
            data: bytes | None = None
            mime = ""
            ext = ""
            used_real = False
            fallback_reason = ""

            if use_real:
                comic_result = await _comic_real_media(prompt, render_params, db)
                if await is_cancelled(db, task_id):
                    logger.info(
                        "media_task_cancelled", task_id=task_id, stage="after_real"
                    )
                    return
                if isinstance(comic_result, dict) and comic_result.get("page"):
                    page = comic_result["page"]
                    data, mime, ext = page[0], page[1], page[2]
                    used_real = True
                    logger.info(
                        "real_provider_succeeded", task_id=task_id, model=model_name
                    )
                else:
                    fallback_reason = (
                        comic_result[1]
                        if isinstance(comic_result, tuple) and len(comic_result) == 2
                        else "漫画真实生成失败或不可用"
                    )

            if data is None and use_real:
                if not fallback_reason:
                    fallback_reason = "真实 Provider 失败或不可用"
                logger.warning(
                    "real_provider_failed, task_id=%s, model=%s, reason=%s",
                    task_id,
                    model_name,
                    fallback_reason[:200],
                )
                raise RuntimeError(f"真实生成失败：{fallback_reason[:300]}")
            if data is None:
                from app.providers.mock import media as _media
                data, mime, ext = _media.render_for(task.task_type, prompt, **render_params)

            now = datetime.now(UTC)
            key = f"{task.user_id}/{now:%Y/%m}/{task.id}.{ext}"

            # 写主资产（用 core.runtime.asset_writer 抽离的工具）
            await write_main_asset_and_finalize(
                db,
                task=task,
                data=data,
                mime=mime,
                ext=ext,
                used_real=used_real,
                model_name=model_name,
                fallback_reason=fallback_reason,
                params=params,
            )

            # Comic 子资产（panels + cover）
            if used_real and data is not None and "comic" in str(task.task_type).lower() and isinstance(comic_result, dict):
                # 上面 write_main_asset_and_finalize 内部已 commit 主资产
                # 重新查 task（已 commit 状态变化）
                task = (
                    await db.execute(
                        select(GenerationTask).where(GenerationTask.id == task_id)
                    )
                ).scalar_one_or_none()
                if task is not None:
                    panel_assets, cover_asset = await _write_comic_subassets(
                        db, task, comic_result, now
                    )
                    # Comic metadata 写到 task.result（不重写主资产字段，只追加 comic 部分）
                    try:
                        existing = json.loads(task.result or "{}")
                    except Exception:
                        existing = {}
                    existing["comic"] = {
                        "panels": cast(list, existing.get("comic", {})).get("panels", []),
                        "assets": panel_assets,
                        "storyboard": (
                            cast(str, comic_result.get("storyboard") or "")
                            if isinstance(comic_result, dict)
                            else ""
                        ),
                        "title": (
                            cast(str, comic_result.get("title") or "")
                            if isinstance(comic_result, dict)
                            else ""
                        ),
                        "cover": cover_asset,
                    }
                    task.result = json.dumps(existing)
                    await db.commit()
                    logger.info(
                        "comic_subassets_written",
                        task_id=task_id,
                        panels=len(panel_assets),
                        has_cover=cover_asset is not None,
                    )

            # 通知：生成完成
            if task is not None and task.task_type in (
                "image", "video", "audio", "music", "comic", "text"
            ):
                await notify_event(
                    {
                        "source": "saios",
                        "type": "saios.generation.succeeded",
                        "severity": "success",
                        "priority": "low",
                        "dedup_key": f"saios:task:{task.id}",
                        "merge_key": f"saios:{task.task_type}",
                        "title": f"{task.task_type} 生成完成",
                        "message": f"模型 {model_name if used_real else 'mock'} · asset {task.id[:8]}",
                        "payload": {
                            "task_id": task.id,
                            "task_type": task.task_type,
                            "model": model_name,
                            "is_real": used_real,
                        },
                    }
                )
            await log_call(
                task_id=task_id,
                task_type=task.task_type if task else "comic",
                provider=model_name if used_real else "mock",
                model=model_name,
                status="fallback" if fallback_reason else "succeeded",
                error_message=fallback_reason,
            )
        except Exception as exc:
            await db.rollback()
            task = (
                await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
            ).scalar_one_or_none()
            if task is not None and task.status != "cancelled":
                task.status = "failed"
                task.error_message = str(exc)[:500]
                task.completed_at = datetime.now(UTC)
                await db.commit()
                if task.task_type in ("image", "video", "audio", "music", "comic", "text"):
                    await notify_event(
                        {
                            "source": "saios",
                            "type": "saios.generation.failed",
                            "severity": "error",
                            "priority": "normal",
                            "dedup_key": f"saios:task:{task.id}",
                            "merge_key": f"saios:{task.task_type}",
                            "title": f"{task.task_type} 生成失败",
                            "message": str(exc)[:200],
                            "payload": {
                                "task_id": task.id,
                                "task_type": task.task_type,
                                "error": str(exc)[:200],
                            },
                        }
                    )
            logger.exception("media_task_failed, task_id=%s", task_id)
            await log_call(
                task_id=task_id,
                task_type=task.task_type if task else "comic",
                provider=model_name if "model_name" in locals() else "",
                model=model_name if "model_name" in locals() else "",
                status="failed",
                error_message=str(exc)[:400],
            )


async def _run_media_task_locked(task_id: str) -> None:
    """任务分派：Comic 走 _run_comic_task；其他委派给 orchestrator。"""
    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if task is None or task.status not in ("queued", "submitting", "processing"):
            return
        task_type = (task.task_type or "").lower()

    if task_type == "comic":
        await _run_comic_task(task_id)
    else:
        from app.core.runtime.orchestrator import run_media_task_main

        await run_media_task_main(task_id)


async def run_media_task(task_id: str) -> None:
    """入口：跨进程 redis_lock + 进程内串行锁。"""
    from app.core.cache import redis_lock

    if not await redis_lock(f"aigc:lock:media_task:{task_id}", ttl=900):
        return
    async with _media_lock():
        await _run_media_task_locked(task_id)
