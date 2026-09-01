"""Core Runtime - 主循环（状态机 + 终态写入 + 通知 + 错误处理）。

从 services/task_runner.py 拆出 `_run_media_task_locked` 中非 Comic 的部分：
- 主循环（状态: queued/submitting/processing → succeeded/failed）
- 真实生成分支（非 comic 调 `_try_real_media`，comic 仍由 task_runner.py 处理）
- 失败处理 + Mock fallback + 终态 + 通知 + log_call

Comic 业务（`_comic_real_media` + panel/cover 落库）**保留在 `task_runner.py`**（P4 移 applications/comic/）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.runtime.asset_writer import (
    write_main_asset_and_finalize,
    _CancelledBeforeFinalize,
)
from app.core.runtime.executor import _try_real_media
from app.core.runtime.governance import notify_event
from app.core.runtime.task import is_cancelled, PROGRESS_STEPS
from app.models.generation_task import GenerationTask
from app.providers.mock import media
from app.services.call_logger import log_call

logger = structlog.get_logger()


_SLOT_BY_TASK: dict[str, str] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "music": "music",
    "text": "text",
}


async def _resolve_model_name(task: GenerationTask) -> str:
    """解析 model_name：空时回退到 hub 链首 default_model（批 13 修复逻辑）。

    batch15: get_active_chain 是协程——原实现漏 await（同步函数里无法 await），
    协程对象 truthy 但 chain[0] 抛 TypeError 被 except 吞掉，恒走「未配置 Provider」。
    本函数改为 async，调用方需 await。
    """
    model_name = (task.model or "").strip()
    if model_name:
        return model_name
    if task.task_type == "image" and settings.DEFAULT_IMAGE_PROVIDER:
        return settings.DEFAULT_IMAGE_PROVIDER
    if task.task_type in ("audio", "music") and settings.DEFAULT_SPEECH_PROVIDER:
        return settings.DEFAULT_SPEECH_PROVIDER
    # 批 13/16 修复：无环境默认时回退到 hub 链首
    try:
        from app.services.model_hub_client import get_active_chain

        slot = _SLOT_BY_TASK.get((task.task_type or "").lower())
        chain = await get_active_chain(slot) if slot else []
        if chain and (
            chain[0].get("base_url") or (chain[0].get("provider_type") or "").lower() == "edge_tts"
        ):
            return str(chain[0].get("default_model") or "hub-candidate")
    except Exception:
        pass
    return ""


async def _progress_loop(
    db: AsyncSession, task: GenerationTask, task_id: str
) -> None:
    """进度上报 + 取消检查循环。"""
    from app.core.runtime.scheduler import _delay
    for pct in PROGRESS_STEPS:
        await _delay()
        # 期间被取消则终止。
        await db.refresh(task)
        if task.status == "cancelled":
            logger.info("media_task_cancelled, task_id=%s", task_id)
            return
        task.progress = pct
        await db.commit()
    # 失败率模拟（默认 0）。
    if settings.MOCK_PROVIDER_FAILURE_RATE > 0 and (
        secrets.randbelow(100) < settings.MOCK_PROVIDER_FAILURE_RATE
    ):
        raise RuntimeError("Mock Provider 模拟失败")


async def run_media_task_main(task_id: str, comic_result_out: dict | None = None) -> None:
    """主循环（不含 Comic 业务）。

    comic_result_out: 可选 dict（如调用方已经处理 comic 业务并写入 comic_result 局部，
        主循环在写终态时会把它合并到 result.json；本批不处理 comic 子资产，
        留给 P4 applications/comic/）。
    """
    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if task is None or task.status not in ("queued", "submitting", "processing"):
            return

        try:
            params: dict[str, object] = json.loads(task.params or "{}")
            prompt = str(params.get("prompt") or params.get("text") or "")

            # ── model_name 解析（含 hub 链首 fallback）──
            model_name = await _resolve_model_name(task)
            use_real = bool(model_name and model_name != "mock")
            if not use_real and model_name != "mock":
                raise RuntimeError(
                    f"未配置可用的{task.task_type} Provider，请在「模型配置」中启用真实模型"
                )

            # P0-2 修复：设 processing 之前先检查 cancel
            if await is_cancelled(db, task_id):
                logger.info("media_task_cancelled, task_id=%s, stage=%s", task_id, "before_processing")
                return

            task.status = "processing"
            await db.commit()

            await _progress_loop(db, task, task_id)

            # ── 真实生成（非 comic）──
            data: bytes | None = None
            mime = ""
            ext = ""
            used_real = False
            fallback_reason = ""

            render_params = {
                k: v for k, v in params.items() if k not in ("prompt", "text", "model")
            }

            if use_real:

                if task.task_type != "comic":
                    # 非 comic：调 _try_real_media
                    real_result = await _try_real_media(
                        task.task_type, prompt, render_params, model_name, db
                    )
                    if await is_cancelled(db, task_id):
                        logger.info(
                            "media_task_cancelled", task_id=task_id, stage="after_real"
                        )
                        return
                    if (
                        isinstance(real_result, tuple)
                        and len(real_result) == 3
                        and real_result[0] is not None
                    ):
                        data, mime, ext = real_result
                        used_real = True
                        logger.info(
                            "real_provider_succeeded",
                            task_id=task_id,
                            model=model_name,
                        )
                    else:
                        fallback_reason = (
                            real_result[1]
                            if isinstance(real_result, tuple) and len(real_result) == 2
                            else "真实 Provider 失败或不可用"
                        )
                # comic：调方方已处理 _comic_real_media，comic_result 在 comic_result_out
                # P0 不在 orchestrator 处理 comic panels/cover 落库（保留在 task_runner.py）

            # ── 真实失败：报错落库，不降级占位 ──
            if data is None and use_real and task.task_type != "comic":
                if not fallback_reason:
                    fallback_reason = "真实 Provider 失败或不可用"
                logger.warning(
                    "real_provider_failed",
                    task_id=task_id,
                    model=model_name,
                    reason=fallback_reason[:200],
                )
                raise RuntimeError(f"真实生成失败：{fallback_reason[:300]}")

            # ── Mock fallback（仅测试/开发隔离通道）──
            if data is None:
                data, mime, ext = media.render_for(
                    task.task_type, prompt, **render_params
                )

            # ── 写主资产 + 终态 ──
            try:
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
            except _CancelledBeforeFinalize:
                return

            # ── 通知：生成完成 ──
            if task.task_type in ("image", "video", "audio", "music", "comic", "text"):
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
                task_type=task.task_type,
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
                task_type=task.task_type if task else "",
                provider=model_name if "model_name" in locals() else "",
                model=model_name if "model_name" in locals() else "",
                status="failed",
                error_message=str(exc)[:400],
            )
